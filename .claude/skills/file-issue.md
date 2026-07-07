# file-issue

File a GitHub issue from conversation context with human review before submission.

## When to use

When the user wants to capture a bug, feature request, or improvement noticed
during a conversation and file it as a GitHub issue without leaving the session
or manually re-typing context.

## Instructions

### Step 1: Extract context from the conversation

Identify the following from the current conversation:

- **Title**: A concise issue title (under 70 characters)
- **Problem**: What went wrong or what is missing
- **Type**: One of bug, feat, refactor, docs, test
- **Files to Modify**: Which source files are affected (use file paths, not line numbers)
- **Expected Behavior**: What should happen instead
- **Acceptance Criteria**: Testable conditions that define done

If any of these are unclear from the conversation, ask the user to clarify
before proceeding.

### Step 2: Strip sensitive data

Before saving the draft, remove all sensitive information using the
patina.issue_draft module. Run via uv run python:

    from patina.issue_draft import strip_sensitive
    sanitized = strip_sensitive(text, names=["CustomerName", "CompanyName"])

Also manually review the draft and remove:
- Real customer or company names (replace with [REDACTED])
- Internal Slack channel names or URLs
- Any credentials, tokens, or API keys
- Real person names that are not project contributors

### Step 3: Save the draft

Save the sanitized draft to ~/.patina/proposed/ using the module.
Run via uv run python:

    from patina.issue_draft import format_draft, strip_sensitive, save_draft

    content = format_draft(
        title="TITLE",
        problem="PROBLEM",
        issue_type="TYPE",
        files=["file1.py", "file2.py"],
        expected_behavior="EXPECTED",
        acceptance_criteria=["criterion 1", "criterion 2"],
    )
    sanitized = strip_sensitive(content, names=["Name1", "Name2"])
    path = save_draft("TITLE", sanitized)

### Step 4: Display the draft for review

Read the saved draft file and display it to the user. Ask whether they want to:
1. Submit - create the GitHub issue now
2. Edit - make changes before submitting
3. Decline - keep the draft in ~/.patina/proposed/ for later

### Step 5a: On approval - submit the issue

Create the issue:

    gh issue create --title "TITLE" --body-file DRAFT_PATH

Then post the implementation detail comment:

    gh issue comment ISSUE_NUMBER --body "**Implementation Detail:**
    **Problem:** PROBLEM_SUMMARY
    **Files:** FILE_LIST
    **Change:** CHANGE_DESCRIPTION"

Display the created issue URL to the user.

### Step 5b: On decline - keep draft

Confirm that the draft remains at its saved path in ~/.patina/proposed/
for later editing. Do not create any issue.

### Step 5c: On edit - modify and re-display

Apply the user requested changes to the draft file, re-display the
updated version, and return to Step 4.
