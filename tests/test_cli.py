import json
from agri_dss.cli import main


def test_demo_cli(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['agri-dss', 'demo'])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result['mode'] == 'demo'
    assert result['decision'] == 'IRRIGATION_REQUIRED'
    assert result['rule_status'] == 'demo_only'


def test_research_cli_rejects_demo(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['agri-dss', 'demo', '--mode', 'research'])
    assert main() == 2
    assert capsys.readouterr().out == ''


def test_fertilizer_cli_saves_normalized_data(monkeypatch, capsys, tmp_path):
    output = tmp_path / 'snapshot.json'
    monkeypatch.setattr('sys.argv', ['agri-dss', 'fertilizer', '--output', str(output)])
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result == json.loads(output.read_text(encoding='utf-8'))
    assert result['pnu_code'] == '5271033027105280033'
    assert result['status'] == 'available'
    assert result['amounts']['basal_n']['value'] == '14.4'
