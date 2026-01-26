# Demo Project

This is a sample project created for demonstrating the Hybrid Local AI Code Reviewer.

## Project Structure

```
demo-project/
├── src/
│   ├── auth/
│   │   └── credentials.py      # Authentication with security issues
│   ├── api/
│   │   ├── user_service.py     # User service with various issues
│   │   └── data_handler.js     # JavaScript file with issues
│   └── main.py                 # Main entry point
└── README.md
```

## Issues in This Project

This project intentionally contains various code issues that the Hybrid Reviewer will detect:

### Security Issues
- Hardcoded passwords (SEC001)
- Hardcoded API keys (SEC002)
- Credentials in URLs

### Performance Issues
- Infinite loops without break conditions (PERF001)

### Code Quality Issues
- Unused imports
- Console print statements instead of logging (LINT001)

## Running the Demo

1. Open this folder in VS Code
2. The Hybrid Reviewer will automatically analyze files as you open them
3. Check the Problems panel to see detected issues
4. Use Command Palette: "Hybrid Reviewer: Analyze File" for manual analysis

## Resetting for Video Recording

To reset all files to their original "Buggy" state (for multiple takes):

```bash
# From the project root
python reset_demo_project.py
```

This will restore:
- `credentials.py`: Hardcoded password & API key
- `user_service.py`: Print statements & Hardcoded secrets
- `data_handler.js`: Infinite loop & Hardcoded secrets


