# Contributing Guidelines

Thank you for your interest in contributing to the PA Trading Bot project!

---

## Code of Conduct

Be respectful, professional, and constructive. This project is open to everyone.

---

## How to Contribute

### 1. Reporting Bugs

Found a bug? Please file an issue with:
- **Title:** Brief description of the bug
- **Description:** What were you doing? What happened? What should happen?
- **Steps to reproduce:** Exact steps to trigger the bug
- **Environment:** Python version, OS, broker, etc.
- **Logs:** Relevant error messages from `logs/bot.log`

Example:
```
Title: Bot crashes when pair has no data

Description:
When running backtest on EUR/USD with missing data, the bot crashes.

Steps:
1. Run: python src/main.py --mode backtest --pairs EUR_USD
2. Bot loads data
3. Bot crashes with KeyError

Expected:
Bot should skip missing data or warn user

Environment:
- Python 3.10
- OANDA
- macOS
```

### 2. Suggesting Features

Have an idea? File an issue with:
- **Title:** Feature request - [brief description]
- **Description:** What problem does this solve? Why is it useful?
- **Examples:** How would a user interact with this?
- **Alternatives:** Any other approaches you considered?

Example:
```
Title: Feature request - Email notifications for large wins/losses

Description:
Currently, users must monitor logs to know about big trades.
It would be useful to get email alerts for:
- Daily loss limit hit
- Large win (>5% of account)
- Large loss (>3% of account)

This would allow users to monitor bot while away.

Examples:
- User sets email in config
- Bot sends email when thresholds hit
- User can adjust thresholds

Alternatives:
- SMS alerts
- Webhook integration
- Discord notifications
```

### 3. Contributing Code

#### Before You Start

1. **Check existing issues/PRs** - Is someone already working on this?
2. **Discuss major changes** - Open an issue first for big features
3. **Read this guide** - Understand our standards
4. **Setup development environment** - See below

#### Development Setup

```bash
# Clone your fork
git clone https://github.com/yourusername/pa-trading-bot.git
cd pa-trading-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate  # Windows

# Install dev dependencies
pip install -r requirements.txt
pip install black flake8 pytest pytest-cov mypy

# Create feature branch
git checkout -b feature/your-feature-name
```

#### Code Standards

**Style:**
- Use `black` for formatting: `black src/`
- Follow PEP 8 (use `flake8`): `flake8 src/`
- Use type hints: `def analyze(data: pd.DataFrame) -> Dict[str, float]:`

**Testing:**
- Write tests for new code
- Run tests: `pytest tests/ -v`
- Aim for >80% coverage: `pytest tests/ --cov=src --cov-report=html`

**Documentation:**
- Document functions with docstrings
- Document classes with examples
- Update README if needed

**Example Function:**
```python
def calculate_position_size(
    account_balance: float,
    risk_percent: float,
    stop_loss_pips: float
) -> float:
    """
    Calculate position size based on account balance and risk parameters.
    
    Args:
        account_balance: Current account balance in USD
        risk_percent: Risk percentage (0.01 = 1%)
        stop_loss_pips: Stop loss distance in pips
    
    Returns:
        Position size in micro-lots
    
    Example:
        >>> calculate_position_size(1000, 0.01, 50)
        200.0  # Risk $10 (1% of $1000), 50 pips = 0.2 micro-lots
    
    Raises:
        ValueError: If parameters are invalid
    """
    if account_balance <= 0:
        raise ValueError("Account balance must be positive")
    if risk_percent <= 0 or risk_percent > 0.1:
        raise ValueError("Risk must be between 0 and 10%")
    if stop_loss_pips <= 5:
        raise ValueError("Stop loss must be > 5 pips")
    
    risk_amount = account_balance * risk_percent
    position_size = risk_amount / stop_loss_pips
    return position_size
```

#### Commit Messages

Write clear, descriptive commits:

```bash
# Good
git commit -m "Add multi-timeframe confluence detection"
git commit -m "Fix: position sizing error with small accounts"
git commit -m "Refactor: simplify price action detection logic"

# Bad
git commit -m "fix stuff"
git commit -m "WIP"
git commit -m "asdf"
```

Format: `[Type]: Brief description (max 50 chars)`

Types:
- `feat:` - New feature
- `fix:` - Bug fix
- `refactor:` - Code refactoring (no behavior change)
- `docs:` - Documentation
- `test:` - Tests
- `perf:` - Performance improvement

#### Creating a Pull Request

1. **Push to your fork:**
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Create PR on GitHub:**
   - Title: Clear description of changes
   - Description: What does it do? Why? Any notes?
   - Link to relevant issue: "Closes #123"
   - Include screenshots/examples if visual changes

3. **PR Template:**
   ```markdown
   ## Description
   Brief explanation of changes.
   
   ## Motivation
   Why is this change needed? What problem does it solve?
   
   ## Changes
   - Changed X to Y
   - Added Z
   - Refactored W
   
   ## Testing
   How did you test this? Manual steps or automated tests?
   
   ## Checklist
   - [ ] Tests pass locally
   - [ ] Code follows style guide
   - [ ] Documentation updated
   - [ ] No breaking changes
   
   ## Related Issues
   Closes #123
   ```

4. **Wait for review:**
   - Respond to feedback promptly
   - Make requested changes
   - Maintainers will merge when ready

---

## Project Structure

```
src/
├── data/           # Data loading, cleaning, storage
├── analysis/       # Price action detection
├── signals/        # Entry signal generation
├── backtest/       # Backtesting engine
├── learning/       # Adaptive learning system
├── risk/           # Risk management
├── broker/         # Broker API connections
└── main.py         # Bot entry point

tests/
├── test_analysis.py
├── test_signals.py
├── test_backtest.py
└── ...

docs/
├── PROJECT_OVERVIEW.md
├── PAIR_SELECTION.md
└── ...
```

When adding features:
1. Add code to appropriate `src/` module
2. Add tests to `tests/` with same name
3. Update docs if user-facing
4. Update README if major feature

---

## Review Process

When you submit a PR:

1. **Automated checks** (GitHub Actions)
   - Tests must pass
   - Code coverage checked
   - Linting verified

2. **Code review** (by maintainers)
   - Does it solve the issue?
   - Does it follow standards?
   - Are there edge cases?
   - Is it documented?

3. **Approval & merge**
   - Usually within 1-2 days
   - May request changes
   - Once approved, maintainer merges

---

## Development Priorities

### Phase 1 (Current)
- ✅ Strategy engine (core PA detection)
- Priority: Core functionality, no edge cases yet

### Phase 2
- ✅ Backtesting framework
- Priority: Accuracy, performance

### Phase 3
- ✅ Paper trading integration
- Priority: Reliability, logging

### Phase 4
- Learning system
- Priority: Stability, validation

### Phase 5
- Live broker integration
- Priority: Safety, monitoring

**Focus contributions in the current phase.**

---

## Areas We Need Help

- **Documentation:** More examples, clearer explanations
- **Testing:** Edge case tests, integration tests
- **Performance:** Optimize backtesting speed
- **Features:** New signal types, market regime detection
- **Brokers:** Support for additional brokers
- **UI/Monitoring:** Dashboard, visualizations

---

## Getting Help

- **General questions?** Open a GitHub discussion
- **Need guidance?** Check existing code/tests
- **Stuck?** Ask in the issue/PR comments
- **Want to discuss design?** Open an issue first

---

## Recognition

Contributors will be:
1. Added to CONTRIBUTORS.md
2. Mentioned in release notes
3. Listed in README

---

## License

By contributing, you agree your code will be licensed under the MIT License.

---

Thank you for contributing! 🙌
