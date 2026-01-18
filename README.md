# Lumina Capital - Multi-Agent Crypto Investment Management

A Python-based multi-agent investment management system using Google Gemini and DeepSeek R1 for autonomous cryptocurrency portfolio management.

## Architecture

This project uses **Hexagonal Architecture** (Ports & Adapters) for maintainability and easy adapter swapping:

```
src/
├── domain/                    # Core business logic (no external dependencies)
│   ├── entities/              # Business objects (Coin, MarketData, Portfolio, etc.)
│   └── ports/                 # Interface definitions (MarketDataPort, TradingPort, etc.)
├── application/               # Use cases and agents
│   ├── agents/                # LLM-powered agents
│   │   ├── gemini_analyst.py  # Market data analysis agent
│   │   └── deepseek_manager.py# Portfolio management agent
│   └── use_cases/             # Business workflows
│       └── investment_cycle.py
├── adapters/                  # External service implementations
│   ├── bitget/                # Bitget API adapter
│   ├── dynamodb/              # AWS DynamoDB adapter
│   ├── llm/                   # LLM adapters (Gemini, DeepSeek)
│   └── lambda_handler.py      # AWS Lambda entry point
└── infrastructure/            # Configuration and logging
    ├── config.py              # Settings management
    ├── container.py           # Dependency injection
    └── logging.py             # Structured logging
```

## Agents

### Gemini Analyst Agent
- **Role**: Market Data Analyst
- **Model**: Google Gemini 2.0 Flash
- **Task**: Analyzes top 200 cryptocurrencies by volume, identifies trends, volatility, and trading opportunities
- **Output**: Structured market analysis stored in DynamoDB

### DeepSeek Manager Agent
- **Role**: Autonomous Portfolio Manager
- **Model**: DeepSeek R1 (Reasoner)
- **Task**: Makes buy/sell/hold decisions with full autonomy over risk management
- **Input**: Gemini analyses + current portfolio state
- **Output**: Trading decisions with reasoning

## Features

- **Multi-Agent System**: Gemini for analysis, DeepSeek for decisions
- **Hexagonal Architecture**: Easy to swap adapters (exchange, storage, LLM)
- **Paper Trading**: Safe testing mode (default)
- **Live Trading**: Execute real trades on Bitget
- **AWS Lambda Ready**: Scheduled execution via CloudWatch Events
- **Local Development**: Docker Compose with DynamoDB Local
- **DynamoDB Storage**: Persistent coin analysis with key format `TICKER-COINNAME`

## Quick Start

### Prerequisites

- Python 3.13.7
- Docker & Docker Compose
- AWS account (for production)
- API keys for:
  - Bitget
  - Google Gemini
  - DeepSeek

### Local Development

1. **Clone and setup environment**:
   ```bash
   cd lumina-capital
   cp .env.example .env
   # Edit .env with your API keys
   ```

2. **Start local DynamoDB**:
   ```bash
   docker-compose up -d dynamodb-local dynamodb-admin
   ```

3. **Install dependencies**:
   ```bash
   pip install -e ".[dev]"
   ```

4. **Run investment cycle**:
   ```bash
   # Full cycle (analysis + decisions) in dry-run mode
   python -m src.main

   # Analysis only
   python -m src.main --mode analyze-only

   # Decisions only (uses existing analyses)
   python -m src.main --mode decide-only

   # With debug logging
   python -m src.main --log-level DEBUG

   # Analyze fewer coins for testing
   python -m src.main --coins 10
   ```

### Docker Execution

```bash
# Build and run
docker-compose build lumina-capital
docker-compose run lumina-capital --mode full --dry-run

# Or run specific mode
docker-compose run lumina-capital --mode analyze-only
```

### AWS Lambda Deployment

1. **Build Lambda image**:
   ```bash
   docker build -f Dockerfile.lambda -t lumina-capital:latest .
   ```

2. **Push to ECR**:
   ```bash
   aws ecr get-login-password | docker login --username AWS --password-stdin $AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com
   docker tag lumina-capital:latest $AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com/lumina-capital:latest
   docker push $AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com/lumina-capital:latest
   ```

3. **Deploy with SAM**:
   ```bash
   sam deploy --guided
   ```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BITGET_API_ACCESS_KEY` | Bitget API key | Required |
| `BITGET_API_SECRET_KEY` | Bitget API secret | Required |
| `BITGET_API_PASSPHRASE` | Bitget API passphrase | Required |
| `GEMINI_API_KEY` | Google Gemini API key | Required |
| `GEMINI_MODEL` | Gemini model name | `gemini-2.0-flash` |
| `DEEPSEEK_API_KEY` | DeepSeek API key | Required |
| `DEEPSEEK_MODEL` | DeepSeek model name | `deepseek-reasoner` |
| `TRADE_MODE` | `paper` or `live` | `paper` |
| `TOP_COINS_COUNT` | Coins to analyze | `200` |
| `USE_LOCAL_DYNAMODB` | Use local DynamoDB | `true` |

## Investment Cycle Workflow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Bitget API    │────▶│  Gemini Agent   │────▶│    DynamoDB     │
│  (Market Data)  │     │   (Analyst)     │     │  (Storage)      │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                        ┌─────────────────┐              │
                        │  DeepSeek Agent │◀─────────────┘
                        │   (Manager)     │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │   Bitget API    │
                        │ (Trade Exec)    │
                        └─────────────────┘
```

1. **Fetch Market Data**: Get top 200 coins by USDT volume from Bitget
2. **Analyze**: Gemini analyzes each coin's price action, trends, volatility
3. **Store**: Save analyses to DynamoDB with key `TICKER-COINNAME`
4. **Decide**: DeepSeek reviews all analyses + portfolio, generates decisions
5. **Execute**: Execute trades (paper mode logs, live mode places orders)

## Security Considerations

- **Never commit `.env`** - Use `.env.example` as template
- **Paper mode by default** - Live trading requires explicit `--live` flag
- **5-second confirmation** - Live trading has a cancellation window
- **AWS Secrets Manager** - Recommended for production API keys
- **Non-root Docker user** - Container runs as unprivileged user

## Development

### Running Tests
```bash
pytest tests/ -v
```

### Code Quality
```bash
# Linting
ruff check src/

# Type checking
mypy src/

# Format
ruff format src/
```

## License

MIT License - See LICENSE file for details.
