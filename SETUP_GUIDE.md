# Strohsack AI - Setup Guide

This guide will help you set up your development environment and get started with the Strohsack AI project.

## Prerequisites

Before you begin, ensure you have the following installed:
- Python 3.10 or higher
- Git
- A code editor (VS Code recommended)
- An Anthropic API key ([Get one here](https://console.anthropic.com/))

## Step 1: Repository Setup

### Option A: If you haven't created a GitHub repository yet

1. Go to GitHub and create a new repository named `strohsack-ai`
2. Keep it private for now (you can make it public later)
3. Do NOT initialize with README (we already have one)

4. In your terminal, navigate to where you want the project:
```bash
cd /path/to/your/projects
```

5. Copy the generated project structure to your desired location

6. Initialize git and push to GitHub:
```bash
git init
git add .
git commit -m "Initial commit: Project structure and documentation"
git branch -M main
git remote add origin https://github.com/yourusername/strohsack-ai.git
git push -u origin main
```

### Option B: If you already have a GitHub repository

1. Clone your repository:
```bash
git clone https://github.com/yourusername/strohsack-ai.git
cd strohsack-ai
```

2. Copy the generated project structure into your cloned repository

## Step 2: Python Virtual Environment

Create and activate a virtual environment:

```bash
# Create virtual environment
python -m venv venv

# Activate it
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

You should see `(venv)` at the beginning of your terminal prompt.

## Step 3: Install Dependencies

Install the required packages:

```bash
# Install core dependencies
pip install -r requirements.txt

# Install development dependencies (optional but recommended)
pip install -r requirements-dev.txt
```

## Step 4: Environment Configuration

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Open `.env` in your code editor and add your Anthropic API key:
```bash
ANTHROPIC_API_KEY=your_actual_api_key_here
```

3. Save the file (it will be ignored by git, so your key stays private)

## Step 5: Test Your Setup

Let's verify everything is working:

```bash
# Test that Python can import the package
python -c "import src.strohsack; print('Package import successful!')"

# Test that environment variables load
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('API Key loaded:', 'ANTHROPIC_API_KEY' in os.environ)"
```

## Step 6: IDE Setup (VS Code)

If you're using VS Code:

1. Open the project folder in VS Code:
```bash
code .
```

2. Install recommended extensions:
   - Python (Microsoft)
   - Pylance (Microsoft)
   - Python Test Explorer
   - GitLens (optional but helpful)

3. Select your virtual environment:
   - Press `Cmd+Shift+P` (Mac) or `Ctrl+Shift+P` (Windows/Linux)
   - Type "Python: Select Interpreter"
   - Choose the interpreter from `./venv/`

4. Install Claude Code (if you haven't already):
   - Follow instructions at https://docs.claude.com/en/docs/claude-code

## Step 7: Personality Profiles (public vs. private)

Strohsack ships a **generic** personality at `src/config/personality.json` —
that's the public bear, with no family/relationship data. The engine loads it by
default, so a fresh clone just works.

If you're running the **at-home build** with family-specific relationship
dynamics, add a private overlay at `src/config/personality.private.json`. It's
gitignored and never published; the loader deep-merges it over the public base
automatically when present (or point `STROHSACK_PERSONALITY` at any profile to
load it directly). See `STROHSACK_PROJECT_PLAN.md` → *Pre-Public Hardening* for
the rationale.

## Step 8: Create Your First Journey Blog Post

Create your first blog post documenting why you're building this:

```bash
# Create the file
touch docs/journey/01-foundation.md
```

Open it in your editor and document:
- Why you're building Strohsack AI
- Your background and goals
- What you hope to learn
- Initial thoughts and excitement

This will be great portfolio content!

## Next Steps

Now that your environment is set up, you're ready to start Phase 0!

### Immediate Tasks:
1. ✅ Repository structure created
2. ✅ Development environment set up
3. ⬜ Simplify personality.json to v0.1
4. ⬜ Write first system prompt
5. ⬜ Build "Hello Strohsack" test
6. ⬜ Create first journey blog post

See [STROHSACK_PROJECT_PLAN.md](../STROHSACK_PROJECT_PLAN.md) for the complete roadmap.

## Troubleshooting

### API Key Issues
If you get authentication errors:
- Double-check your `.env` file has the correct key
- Ensure no extra spaces around the `=` sign
- Restart your terminal/IDE after changing `.env`

### Import Errors
If Python can't find your modules:
- Make sure you're in the project root directory
- Verify your virtual environment is activated
- Check that all `__init__.py` files exist

### Git Issues
If you have trouble pushing to GitHub:
- Make sure you've created the repository on GitHub first
- Check that you've set up SSH keys or HTTPS credentials
- Try: `git remote -v` to see if your remote is configured

## Getting Help

- **Anthropic API Docs:** https://docs.anthropic.com/
- **Python Documentation:** https://docs.python.org/3/
- **GitHub Docs:** https://docs.github.com/

## Project Structure Overview

```
strohsack-ai/
├── docs/              # All documentation
├── src/               # Source code
│   ├── strohsack/    # Main package
│   └── config/       # Configuration files
├── tests/            # Test files
├── notebooks/        # Jupyter notebooks for experiments
├── demos/            # Demo videos and screenshots
└── scripts/          # Utility scripts
```

---

**Ready to start coding?** Let's build Strohsack! 🐻🍯
