# Project Constraints
- Python 3.12+
- Use uv for package management
- Linting and Formatting should be done using ruff

# Development Rules
- Before writing code state how you will test and verify it.
- Always lint and run tests immediately after making changes, never assume your changes work or that the code is formatted correctly.
- Always make small git commits with a defined logical scope, do not combine features into a single mega commit.
- Always use type hints and annotations
- Document your work using doc strings and comments as you work, focus commenting on complicated or unclear work you do
- All code must meet the standards outlined in PEP 8 excluding the rule about maximum line length (ruff rule E501)
- Never write a real secret (API key, password, token) to a file via Bash/heredoc/python -c, even to avoid printing it. Editing a tracked file outside the Write/Edit tools triggers the harness's "changed on disk" diff notification, which echoes the full file content — including the secret — back into the conversation. Always use the Write or Edit tool directly for any file containing a real secret.