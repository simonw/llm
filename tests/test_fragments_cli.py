from click.testing import CliRunner
from llm.cli import cli
import yaml


def test_fragments_set_show_remove(user_path):
    runner = CliRunner()
    with runner.isolated_filesystem():
        open("fragment1.txt", "w").write("Hello fragment 1")

        # llm fragments --aliases should return nothing
        assert runner.invoke(cli, ["fragments", "list", "--aliases"]).output == ""
        assert (
            runner.invoke(cli, ["fragments", "set", "f1", "fragment1.txt"]).exit_code
            == 0
        )
        result1 = runner.invoke(cli, ["fragments", "show", "f1"])
        assert result1.exit_code == 0
        assert result1.output == "Hello fragment 1\n"

        # Should be in the list now
        def get_list():
            result2 = runner.invoke(cli, ["fragments", "list"])
            assert result2.exit_code == 0
            return yaml.safe_load(result2.output)

        # And in llm fragments --aliases
        assert "f1" in runner.invoke(cli, ["fragments", "list", "--aliases"]).output

        loaded1 = get_list()
        assert set(loaded1[0].keys()) == {
            "aliases",
            "content",
            "datetime_utc",
            "source",
            "hash",
        }
        assert loaded1[0]["content"] == "Hello fragment 1"
        assert loaded1[0]["aliases"] == ["f1"]

        # Show should work against both alias and hash
        for key in ("f1", loaded1[0]["hash"]):
            result3 = runner.invoke(cli, ["fragments", "show", key])
            assert result3.exit_code == 0
            assert result3.output == "Hello fragment 1\n"

        # But not for an invalid alias
        result4 = runner.invoke(cli, ["fragments", "show", "badalias"])
        assert result4.exit_code == 1
        assert "Fragment 'badalias' not found" in result4.output

        # Remove that alias
        result5 = runner.invoke(cli, ["fragments", "remove", "f1"])
        assert result5.exit_code == 0
        # Should still be in list but no alias
        loaded2 = get_list()
        assert loaded2[0]["aliases"] == []
        assert loaded2[0]["content"] == "Hello fragment 1"

        # And --aliases list should be empty
        assert runner.invoke(cli, ["fragments", "list", "--aliases"]).output == ""
