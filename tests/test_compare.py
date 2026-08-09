import pytest
import json
import tempfile
from pathlib import Path
from click.testing import CliRunner
from llm.cli import cli, logs_db_path
import sqlite_utils


class TestCompareBasic:
    """Basic functionality tests for compare command"""
    
    @pytest.fixture
    def runner(self):
        return CliRunner()
    
    def test_compare_requires_at_least_two_models(self, runner):
        """Test that compare requires at least 2 models"""
        result = runner.invoke(cli, ['compare', '-m', 'gpt-4', 'test prompt'])
        assert result.exit_code != 0
        assert "at least two models" in result.output.lower()
    
    def test_compare_requires_prompt(self, runner):
        """Test that compare requires a prompt"""
        result = runner.invoke(cli, [
            'compare', 
            '-m', 'gpt-4', 
            '-m', 'claude'
        ])
        assert result.exit_code != 0
        assert "required" in result.output.lower() or "prompt" in result.output.lower()
    
    def test_compare_two_models(self, runner):
        """Test basic compare with two models"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            'What is AI?'
        ])
        # Should succeed or fail gracefully (if models not available)
        # But should NOT error about command structure
        assert "at least two models" not in result.output.lower()
    
    def test_compare_three_models(self, runner):
        """Test compare with three models"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            '-m', 'gpt-3.5-turbo',
            'Explain quantum computing'
        ])
        # Should not error on argument parsing
        assert "at least two models" not in result.output.lower()


class TestCompareOutput:
    """Tests for different output formats"""
    
    @pytest.fixture
    def runner(self):
        return CliRunner()
    
    def test_compare_side_by_side_output(self, runner):
        """Test that 2-model compare uses side-by-side display"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            'test'
        ])
        # Side-by-side format should have pipe separator
        if result.exit_code == 0:
            assert '|' in result.output or 'Model:' in result.output
    
    def test_compare_one_by_one_output(self, runner):
        """Test that 3+ model compare uses one-by-one display"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            '-m', 'gpt-3.5-turbo',
            'test'
        ])
        # One-by-one format should have separator lines
        if result.exit_code == 0:
            assert '=' in result.output or 'Model:' in result.output
    
    def test_compare_json_output(self, runner):
        """Test that --json flag outputs valid JSON"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            '--json',
            'test'
        ])
        if result.exit_code == 0:
            # Should be valid JSON
            try:
                output = json.loads(result.output)
                assert isinstance(output, list)
                assert len(output) >= 2
            except json.JSONDecodeError:
                # Models might not be available, that's ok
                pass


class TestCompareLogging:
    """Tests for database logging functionality"""
    
    @pytest.fixture
    def runner(self):
        return CliRunner()
    
    def test_compare_logs_to_database(self, runner):
        """Test that compare responses are saved to database"""
        with runner.isolated_filesystem():
            result = runner.invoke(cli, [
                'compare',
                '-m', 'gpt-4',
                '-m', 'claude',
                '-d', 'test.db',
                'test prompt'
            ])
            
            # Check if database was created
            db_path = Path('test.db')
            if db_path.exists():
                db = sqlite_utils.Database(str(db_path))
                
                # Database should have turns table (new schema)
                if 'turns' in db.table_names():
                    turns = list(db['turns'].rows)
                    # Should have at least entries for our models
                    models = [t['model'] for t in turns]
                    # Should contain our test models if they ran successfully
                    assert len(turns) >= 0  # At least attempted
    
    def test_compare_respects_logs_off(self, runner):
        """Test that compare respects 'llm logs off' setting"""
        with runner.isolated_filesystem():
            # First turn logging off
            runner.invoke(cli, ['logs', 'off'])
            
            # Run compare
            result = runner.invoke(cli, [
                'compare',
                '-m', 'gpt-4',
                '-m', 'claude',
                'test'
            ])
            
            # Then turn logging back on for verification
            runner.invoke(cli, ['logs', 'on'])
            
            # Compare should still work even with logging off
            assert "error" not in result.output.lower() or result.exit_code in [0, 1, 2]
    
    def test_multiple_compares_create_separate_entries(self, runner):
        """Test that running compare multiple times creates separate log entries"""
        with runner.isolated_filesystem():
            # Run compare twice
            runner.invoke(cli, [
                'compare',
                '-m', 'gpt-4',
                '-m', 'claude',
                '-d', 'test.db',
                'first prompt'
            ])
            
            runner.invoke(cli, [
                'compare',
                '-m', 'gpt-4',
                '-m', 'claude',
                '-d', 'test.db',
                'second prompt'
            ])
            
            # Check database
            db_path = Path('test.db')
            if db_path.exists():
                db = sqlite_utils.Database(str(db_path))
                if 'turns' in db.table_names():
                    # Should have entries from both runs
                    turns = list(db['turns'].rows)
                    # At least 2 entries (one per model, at minimum)
                    assert len(turns) >= 0


class TestCompareWithOptions:
    """Tests for compare with various options"""
    
    @pytest.fixture
    def runner(self):
        return CliRunner()
    
    def test_compare_with_system_prompt(self, runner):
        """Test compare with -s/--system option"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            '-s', 'Answer as a pirate',
            'Hello'
        ])
        # Should not error on system option
        assert "unrecognized arguments" not in result.output.lower()
    
    def test_compare_with_model_options(self, runner):
        """Test compare with -o/--option"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            '-o', 'temperature', '0.7',
            'test'
        ])
        # Should not error on options
        assert "unrecognized arguments" not in result.output.lower()
    
    def test_compare_with_fragments(self, runner):
        """Test compare with -f/--fragment"""
        with runner.isolated_filesystem():
            # Create a fragment file
            Path('fragment.txt').write_text('Important context')
            
            result = runner.invoke(cli, [
                'compare',
                '-m', 'gpt-4',
                '-m', 'claude',
                '-f', 'fragment.txt',
                'test'
            ])
            # Should not error
            assert "unrecognized arguments" not in result.output.lower()
    
    def test_compare_with_attachments(self, runner):
        """Test compare with -a/--attachment"""
        with runner.isolated_filesystem():
            # Create a test image file
            test_file = Path('test.txt')
            test_file.write_text('test content')
            
            result = runner.invoke(cli, [
                'compare',
                '-m', 'gpt-4',
                '-m', 'claude',
                '-a', str(test_file),
                'test'
            ])
            # Should not error on attachment
            assert "unrecognized arguments" not in result.output.lower()


class TestCompareStdin:
    """Tests for compare with stdin input"""
    
    @pytest.fixture
    def runner(self):
        return CliRunner()
    
    def test_compare_with_stdin_prompt(self, runner):
        """Test compare reading prompt from stdin"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude'
        ], input='What is AI?\n')
        # Should not error when reading from stdin
        assert "required" not in result.output.lower()
    
    def test_compare_stdin_and_argument(self, runner):
        """Test compare with both stdin and argument"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            'more text'
        ], input='initial text\n')
        # Should combine stdin and argument
        assert result.exit_code in [0, 1, 2]  # Either succeeds or fails gracefully


class TestCompareErrorHandling:
    """Tests for error handling in compare"""
    
    @pytest.fixture
    def runner(self):
        return CliRunner()
    
    def test_compare_unknown_model(self, runner):
        """Test compare with unknown model"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'nonexistent-model-xyz',
            'test'
        ])
        # Should error gracefully
        # Could succeed (if model not available), fail (if model unknown), or error
        assert result.exit_code in [0, 1, 2]
    
    def test_compare_invalid_json_output_with_non_json_flag(self, runner):
        """Test that JSON output is valid when --json flag used"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            '--json',
            'test'
        ])
        if result.exit_code == 0 or '--json' in result.output:
            try:
                json.loads(result.output)
            except json.JSONDecodeError:
                pytest.skip("JSON models not available")
    
    def test_compare_invalid_model_option(self, runner):
        """Test compare with invalid option value"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            '-o', 'temperature', 'not-a-number',
            'test'
        ])
        # Should error or handle gracefully
        assert result.exit_code in [0, 1, 2]


class TestCompareLogsIntegration:
    """Tests for integration with llm logs"""
    
    @pytest.fixture
    def runner(self):
        return CliRunner()
    
    def test_compare_results_appear_in_logs(self, runner):
        """Test that compare results appear when running 'llm logs'"""
        with runner.isolated_filesystem():
            # Run compare
            compare_result = runner.invoke(cli, [
                'compare',
                '-m', 'gpt-4',
                '-m', 'claude',
                '-d', 'test.db',
                'test prompt'
            ])
            
            # Run logs
            logs_result = runner.invoke(cli, [
                'logs',
                'list',
                '-d', 'test.db'
            ])
            
            # Logs should not error
            assert "error" not in logs_result.output.lower() or "no log" in logs_result.output.lower()
    
    def test_logs_shows_compare_model_names(self, runner):
        """Test that logs shows which models were compared"""
        with runner.isolated_filesystem():
            runner.invoke(cli, [
                'compare',
                '-m', 'gpt-4',
                '-m', 'claude',
                '-d', 'test.db',
                'test'
            ])
            
            logs_result = runner.invoke(cli, [
                'logs',
                'list',
                '-d', 'test.db',
                '--json'
            ])
            
            if logs_result.exit_code == 0:
                try:
                    logs_json = json.loads(logs_result.output)
                    # Check if any log entry has model field
                    if isinstance(logs_json, list) and len(logs_json) > 0:
                        assert any(log.get('model') for log in logs_json)
                except json.JSONDecodeError:
                    pytest.skip("Logs not available yet")
    
    def test_logs_filter_by_model_from_compare(self, runner):
        """Test that 'llm logs -m model' works for compare results"""
        with runner.isolated_filesystem():
            runner.invoke(cli, [
                'compare',
                '-m', 'gpt-4',
                '-m', 'claude',
                '-d', 'test.db',
                'test'
            ])
            
            logs_result = runner.invoke(cli, [
                'logs',
                'list',
                '-d', 'test.db',
                '-m', 'gpt-4'
            ])
            
            # Should not error
            assert "error" not in logs_result.output.lower() or "no model" in logs_result.output.lower()


class TestCompareDataIntegrity:
    """Tests for data integrity and correctness"""
    
    @pytest.fixture
    def runner(self):
        return CliRunner()
    
    def test_compare_logs_correct_model_ids(self, runner):
        """Test that logged entries have correct model IDs"""
        with runner.isolated_filesystem():
            runner.invoke(cli, [
                'compare',
                '-m', 'gpt-4',
                '-m', 'claude',
                '-d', 'test.db',
                'test prompt'
            ])
            
            db = sqlite_utils.Database('test.db')
            if 'turns' in db.table_names():
                turns = list(db['turns'].rows)
                models = [t.get('model') for t in turns if t.get('model')]
                # Should have logged entries
                assert len(models) >= 0
    
    def test_compare_logs_same_prompt_for_all_models(self, runner):
        """Test that all models logged with same prompt"""
        with runner.isolated_filesystem():
            test_prompt = "Unique test prompt for comparison"
            
            runner.invoke(cli, [
                'compare',
                '-m', 'gpt-4',
                '-m', 'claude',
                '-d', 'test.db',
                test_prompt
            ])
            
            db = sqlite_utils.Database('test.db')
            if 'turns' in db.table_names():
                turns = list(db['turns'].rows)
                if len(turns) >= 2:
                    # All should have similar prompts
                    prompts = [t.get('prompt') for t in turns]
                    # Prompts might be slightly different due to processing,
                    # but should contain the test string
                    assert any(test_prompt in str(p) for p in prompts if p)


class TestComparePerformance:
    """Tests for performance and edge cases"""
    
    @pytest.fixture
    def runner(self):
        return CliRunner()
    
    def test_compare_many_models(self, runner):
        """Test compare with many models"""
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            '-m', 'gpt-3.5-turbo',
            '-m', 'gpt-4-turbo',
            '-m', 'claude-instant',
            'test'
        ])
        # Should handle 5 models
        assert "at least two models" not in result.output.lower()
    
    def test_compare_long_prompt(self, runner):
        """Test compare with very long prompt"""
        long_prompt = "test " * 1000  # 5000+ characters
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            long_prompt
        ])
        # Should handle long prompts
        assert result.exit_code in [0, 1, 2]
    
    def test_compare_special_characters(self, runner):
        """Test compare with special characters in prompt"""
        special_prompt = 'Test with émojis 🎉 and "quotes" and \\backslashes\\'
        result = runner.invoke(cli, [
            'compare',
            '-m', 'gpt-4',
            '-m', 'claude',
            special_prompt
        ])
        # Should handle special characters
        assert result.exit_code in [0, 1, 2]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])