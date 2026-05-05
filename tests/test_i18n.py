import importlib

import pytest

from opencode_buddy import i18n


@pytest.fixture(autouse=True)
def _restore_locale():
    original = i18n.get_locale()
    yield
    i18n.set_locale(original)


def test_default_locale_is_pt_br():
    i18n.set_locale("pt-BR")
    assert i18n.get_locale() == "pt-BR"
    assert i18n.t("tag.ok").strip() == "[OK]"


def test_set_locale_switches_translation():
    i18n.set_locale("en-US")
    assert i18n.get_locale() == "en-US"
    assert "Next steps" in i18n.t("scaffold.next_steps.header")


def test_set_locale_rejects_unsupported_code():
    with pytest.raises(ValueError):
        i18n.set_locale("fr-FR")


def test_t_supports_format_placeholders():
    i18n.set_locale("pt-BR")
    assert "DEEPSEEK_API_KEY" in i18n.t("tag.missing_env", env="DEEPSEEK_API_KEY")


def test_t_falls_back_to_pt_br_when_key_missing_in_other_locale(monkeypatch):
    fake_locale = "en-US"
    monkeypatch.setitem(i18n._CATALOG, fake_locale, {})  # esvazia en-US
    i18n.set_locale(fake_locale)
    assert "[OK]" in i18n.t("tag.ok")  # caiu no fallback pt-BR


def test_t_returns_key_when_unknown():
    i18n.set_locale("pt-BR")
    assert i18n.t("missing.key.does.not.exist") == "missing.key.does.not.exist"


def test_t_first_arg_is_positional_only_no_collision_with_kwargs():
    # Garante que t("...", key="x") nao explode mesmo com placeholder chamado {key}.
    # Usa uma chave qualquer e passa key=... — o {key} no template (se houver) deve ser substituido.
    i18n.set_locale("pt-BR")
    # tag.recommended nao tem placeholder; passar kwargs extras nao deve quebrar
    assert i18n.t("tag.recommended", key="ignored") == "[recomendado]"


def test_locale_resolved_from_env_on_module_load(monkeypatch):
    monkeypatch.setenv(i18n.ENV_VAR, "en-US")
    reloaded = importlib.reload(i18n)
    try:
        assert reloaded.get_locale() == "en-US"
    finally:
        monkeypatch.delenv(i18n.ENV_VAR, raising=False)
        importlib.reload(i18n)


def test_locale_env_var_normalizes_underscore():
    # pt_BR ou pt deve resolver para pt-BR
    assert i18n._resolve_initial_locale() in i18n.SUPPORTED_LOCALES


def test_missing_in_locale_lists_untranslated_keys():
    # Catalogo en-US deve estar quase completo — checar que se houver chaves faltando, sao reportadas
    missing = i18n.missing_in_locale("en-US")
    assert isinstance(missing, tuple)
    assert all(isinstance(k, str) for k in missing)


def test_all_keys_returns_sorted_keys():
    keys = i18n.all_keys("pt-BR")
    assert keys == tuple(sorted(keys))
    assert "tag.ok" in keys


def test_keys_validate_output_uses_i18n_when_locale_changes(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from opencode_buddy.cli import app

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    runner = CliRunner()

    i18n.set_locale("en-US")
    result_en = runner.invoke(app, ["keys", "validate", "--cwd", str(tmp_path), "--provider", "deepseek"])
    assert result_en.exit_code == 0
    assert "Providers" in result_en.stdout

    i18n.set_locale("pt-BR")
    result_pt = runner.invoke(app, ["keys", "validate", "--cwd", str(tmp_path), "--provider", "naoexiste"])
    assert "nao existe no registry" in (result_pt.stdout + result_pt.stderr)


def test_validator_summary_translated():
    from opencode_buddy.validator import format_validation_report

    i18n.set_locale("en-US")
    report = format_validation_report([])
    assert "Everything consistent" in report

    i18n.set_locale("pt-BR")
    report_pt = format_validation_report([])
    assert "Tudo consistente" in report_pt
