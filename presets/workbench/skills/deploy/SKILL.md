---
name: deploy
description: >
  Deploy the portfolio chat agent Lambda function to AWS. Use when the user asks
  to deploy, redeploy, push to Lambda, update the chat agent, or after updating
  context files or lambda_function.py. Rebuilds the knowledge base, packages
  dependencies, and deploys to AWS Lambda.
---

# Deploy Skill

Rebuild and deploy the portfolio chat agent Lambda function to AWS.

## When to Use

- After updating any file in `WebContent/context/`
- After modifying `lambda/lambda_function.py`
- When the user says "deploy", "redeploy", "push to Lambda", or "update the chat agent"

## Workflow

1. **Rebuild knowledge base** — Regenerate `lambda/knowledge_base.json` from context files
2. **Clean previous build** — Remove old `package/` directory and `deployment.zip`
3. **Install dependencies** — Install Python packages for Linux/x86_64 target
4. **Package** — Copy handler and knowledge base into package, create zip
5. **Deploy** — Update Lambda function code via AWS CLI
6. **Verify** — Confirm deployment succeeded

## Commands

### Step 1: Rebuild Knowledge Base

```bash
python scripts/build_knowledge_base.py
```

Verify output shows expected project count and no errors.

### Step 2: Clean and Install Dependencies

```bash
cd lambda
rm -rf package/ deployment.zip
pip install -r requirements.txt -t package/ \
  --platform manylinux2014_x86_64 \
  --only-binary=:all: \
  --implementation cp \
  --python-version 3.12
```

The `--platform` and `--only-binary` flags ensure compiled extensions are built for Amazon Linux, not macOS.

### Step 3: Package Deployment Zip

```bash
cp lambda_function.py knowledge_base.json package/
cd package && zip -r ../deployment.zip . && cd ..
```

### Step 4: Deploy to Lambda

```bash
aws lambda update-function-code \
  --function-name portfolio-chat-agent \
  --zip-file fileb://lambda/deployment.zip
```

Run this from the repository root so the `fileb://` path resolves correctly.

### Step 5: Verify

Check that the response includes:

- `"LastUpdateStatus": "InProgress"` or `"Successful"`
- `"FunctionName": "portfolio-chat-agent"`
- Updated `CodeSha256` value

## Configuration

| Setting       | Value                  |
| ------------- | ---------------------- |
| Function name | `portfolio-chat-agent` |
| Runtime       | `python3.12`           |
| Region        | `us-west-1`            |
| Memory        | 256 MB                 |
| Timeout       | 30 seconds             |
| Architecture  | `x86_64`               |

## Rules

- **Never print or log the Anthropic API key.** If the AWS CLI response includes environment variables, do not echo them back to the user.
- **Always rebuild the knowledge base first.** Even if only `lambda_function.py` changed, rebuilding ensures the knowledge base is current.
- **Run from the repository root.** The `fileb://` path in the deploy command is relative to the working directory.
- **Do not modify Lambda environment variables** unless the user explicitly asks to update the API key.

## Troubleshooting

| Problem                                          | Solution                                                                                          |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| `No module named 'pydantic_core._pydantic_core'` | Missing `--platform` flag during pip install — dependencies were built for macOS instead of Linux |
| `Unable to load paramfile fileb://`              | Wrong working directory — run the deploy command from the repository root                         |
| `ResourceNotFoundException`                      | Lambda function doesn't exist yet — create it with `aws lambda create-function` first             |
| `CodeStorageExceededException`                   | Deployment zip too large — check for unnecessary dependencies in `requirements.txt`               |
