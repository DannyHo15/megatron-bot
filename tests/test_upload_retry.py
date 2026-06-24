from types import SimpleNamespace

import httpx
import pytest
from openai import NotFoundError

from src import vector_store


class _FakeFiles:
    def __init__(self):
        self.created: list[str] = []
        self.deleted: list[str] = []
        self._n = 0

    def create(self, file, purpose):
        self._n += 1
        fid = f"file-{self._n:02d}"
        self.created.append(fid)
        return SimpleNamespace(id=fid)

    def delete(self, file_id):
        self.deleted.append(file_id)


class _FakeVSFiles:
    def __init__(self, fail_first_n: int):
        self._left = fail_first_n
        self.attached: list[str] = []

    def create_and_poll(self, *, vector_store_id, file_id, attributes):
        if self._left > 0:
            self._left -= 1
            raise NotFoundError(
                message=f"No file found with id '{file_id}'",
                response=httpx.Response(404, request=httpx.Request("GET", "https://api.openai.com")),
                body=None,
            )
        self.attached.append(file_id)


@pytest.fixture
def fake_client(monkeypatch, tmp_path):
    monkeypatch.setattr(vector_store, "UPLOAD_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(vector_store.time, "sleep", lambda _s: None)
    f = tmp_path / "x.md"
    f.write_text("hi")
    return f


def test_upload_succeeds_first_try(fake_client, monkeypatch):
    files = _FakeFiles()
    vsf = _FakeVSFiles(fail_first_n=0)
    monkeypatch.setattr(vector_store.client, "files", files)
    monkeypatch.setattr(vector_store.client.vector_stores, "files", vsf)

    fid = vector_store.upload(fake_client, article_id="a1", content_hash="h", url="u")
    assert fid == "file-01"
    assert vsf.attached == ["file-01"]
    assert files.deleted == []


def test_upload_retries_then_succeeds(fake_client, monkeypatch):
    files = _FakeFiles()
    vsf = _FakeVSFiles(fail_first_n=2)  # 2 races, succeeds on 3rd
    monkeypatch.setattr(vector_store.client, "files", files)
    monkeypatch.setattr(vector_store.client.vector_stores, "files", vsf)

    fid = vector_store.upload(fake_client, article_id="a1", content_hash="h", url="u")
    assert fid == "file-03"
    assert files.created == ["file-01", "file-02", "file-03"]
    assert files.deleted == ["file-01", "file-02"]  # orphans cleaned


def test_upload_gives_up_after_max(fake_client, monkeypatch):
    files = _FakeFiles()
    vsf = _FakeVSFiles(fail_first_n=99)
    monkeypatch.setattr(vector_store.client, "files", files)
    monkeypatch.setattr(vector_store.client.vector_stores, "files", vsf)

    with pytest.raises(NotFoundError):
        vector_store.upload(fake_client, article_id="a1", content_hash="h", url="u")
    assert len(files.created) == 3
    assert len(files.deleted) == 3
