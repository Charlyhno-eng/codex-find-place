import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from osint_picture import app
from osint_picture.frontend import prepare_frontend


def test_source_startup_installs_once_and_rebuilds(monkeypatch, tmp_path):
    (tmp_path / 'frontend/src').mkdir(parents=True)
    (tmp_path / 'package.json').write_text('{}')
    lock = tmp_path / 'package-lock.json'
    lock.write_text('{}')
    monkeypatch.setattr('osint_picture.frontend.shutil.which', lambda _: '/usr/bin/npm')
    commands = []

    def run(command, **kwargs):
        assert kwargs == {'cwd': tmp_path, 'check': True}
        commands.append(command[1:])
        (tmp_path / 'node_modules').mkdir(exist_ok=True)

    monkeypatch.setattr('osint_picture.frontend.subprocess.run', run)
    prepare_frontend(tmp_path)
    prepare_frontend(tmp_path)
    assert commands == [['ci', '--no-audit', '--no-fund'], ['run', 'build'], ['run', 'build']]
    lock.write_text('{"changed":true}')
    prepare_frontend(tmp_path)
    assert commands[-2:] == [['ci', '--no-audit', '--no-fund'], ['run', 'build']]


def test_packaged_frontend_needs_no_npm(monkeypatch, tmp_path):
    output = tmp_path / 'osint_picture/static/dist/index.html'
    output.parent.mkdir(parents=True)
    output.write_text('<html></html>')
    run = Mock()
    monkeypatch.setattr('osint_picture.frontend.subprocess.run', run)
    prepare_frontend(tmp_path)
    run.assert_not_called()


def test_failed_build_does_not_start_server(monkeypatch):
    def fail(_):
        raise subprocess.CalledProcessError(1, ['npm', 'run', 'build'])

    monkeypatch.setattr(app, 'prepare_frontend', fail)
    server = Mock()
    monkeypatch.setattr(app.uvicorn, 'run', server)
    with pytest.raises(SystemExit, match='Application startup failed'):
        app.main()
    server.assert_not_called()


def test_entry_point_prepares_frontend_before_starting(monkeypatch):
    steps = []
    monkeypatch.setattr(app, 'prepare_frontend', lambda project: steps.append(('frontend', project)))
    monkeypatch.setattr(app.uvicorn, 'run', lambda *args, **kwargs: steps.append(('server', kwargs)))
    app.main()
    assert steps == [('frontend', app.ROOT.parent), ('server', {'host': '127.0.0.1', 'port': 8000})]
