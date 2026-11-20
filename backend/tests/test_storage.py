import uuid

import pytest

from app.errors import NotFoundError
from app.services.storage_service import project_dir


def test_project_path_stays_inside_the_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    project_id = str(uuid.uuid4())
    path = project_dir(project_id)
    assert path.is_relative_to(tmp_path)
    assert path.name == project_id


def test_rejects_path_traversal():
    with pytest.raises(NotFoundError):
        project_dir("../secrets")
