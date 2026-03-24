# AI-Powered GitHub Issue Triage

An AI-powered service that automatically classifies and prioritizes GitHub issues using large language models (LLMs).

# Overview

Managing GitHub issues can become overwhelming as projects scale. Manual triage is time-consuming and inconsistent, especially in fast-moving teams.

This project introduces an intelligent triage assistant that:

  - Classifies new issues (bug, feature request, question, documentation, etc.)
  
  - Assigns priority levels
  
  - Suggests relevant labels
  
  - Posts a structured triage summary as a comment

The system integrates directly with GitHub using webhooks and processes issues in real time.

## Key Features (MVP Scope)

  - GitHub webhook integration

  - Automated issue classification

  - Priority inference

  - Suggested label generation

  - Structured triage summary comment

## Architecture (High-Level)

1. A new GitHub issue is created.

2. GitHub sends a webhook event to the backend service.

3. The backend extracts issue data (title + description).

4. An LLM analyzes the content and returns structured triage metadata.

5. The service applies labels and posts a triage summary comment.

## Status

🚧 Currently in active development (MVP phase).

Planned future improvements include:

  - Duplicate issue detection

  - Team/owner suggestion

  - Confidence scoring

  - Evaluation and logging framework

## Tech Stack 

  - Python
  
  - FastAPI (backend service)
  
  - GitHub Webhooks & API
  
  - LLM integration (OpenAI / compatible models)
  
  - Ngrok (for local webhook testing)

### Author

Hanna Hunde
*(Software Engineer | Aspiring AI Engineer)*
