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
│   ├── fundamental/           # Fundamental data adapters (CoinGecko, Alternative.me)
│   ├── llm/                   # LLM adapters (Gemini, DeepSeek)
│   └── storage/               # JSON storage adapter
└── infrastructure/            # Configuration and logging
    ├── config.py              # Settings management
    ├── container.py           # Dependency injection
    └── logging.py             # Structured logging
```

## Agents

### Gemini Analyst Agent
- **Role**: Market Data Analyst
- **Model**: Google Gemini 2.0 Flash / Gemini 3 Pro
- **Task**: Analyzes top N cryptocurrencies by volume + portfolio holdings
- **Features**:
  - Technical analysis (trends, volatility, support/resistance)
  - Fundamental data integration (Fear & Greed Index, CoinGecko metrics)
  - Auto-retry with exponential backoff on API errors (503, 429, etc.)
- **Output**: Structured market analysis stored in JSON/DynamoDB

### DeepSeek Manager Agent
- **Role**: Autonomous Portfolio Manager
- **Model**: DeepSeek R1 (Reasoner)
- **Task**: Makes buy/sell/hold decisions with full autonomy over risk management
- **Input**: Gemini analyses + current portfolio state (filtered by min balance)
- **Output**: Trading decisions with reasoning

## Features

- **Multi-Agent System**: Gemini for analysis, DeepSeek for decisions
- **Hexagonal Architecture**: Easy to swap adapters (exchange, storage, LLM)
- **Fundamental Analysis**: Fear & Greed Index + CoinGecko metrics with caching
- **Auto-Lookup**: Unknown tickers automatically discovered via CoinGecko search
- **Portfolio Integration**: Analyze both top N coins AND current holdings
- **Configurable Filtering**: Min balance threshold for portfolio positions
- **Paper Trading**: Safe testing mode (default)
- **Live Trading**: Execute real trades on Bitget
- **Flexible Storage**: JSON (local) or DynamoDB (production)
- **Auto-Retry**: Exponential backoff on transient API errors

## Quick Start

### Prerequisites

- Python 3.13+
- API keys for:
  - Bitget
  - Google Gemini
  - DeepSeek
  - CoinGecko (optional, for higher rate limits)

### Local Development

1. **Clone and setup environment**:
   ```bash
   cd lumina-capital
   cp .env.example .env
   # Edit .env with your API keys
   ```

2. **Install dependencies**:
   ```bash
   pip install -e ".[dev]"
   ```

3. **Run investment cycle**:
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
| `STORAGE_TYPE` | `json` or `dynamodb` | `json` |
| `JSON_STORAGE_PATH` | Path to JSON storage file | `data/coin_analyses.json` |
| `ENABLE_FUNDAMENTAL_ANALYSIS` | Enable Fear & Greed + CoinGecko | `true` |
| `FUNDAMENTAL_CACHE_PATH` | Path to fundamental data cache | `data/fundamental_cache.json` |
| `COINGECKO_API_KEY` | CoinGecko API key (optional) | - |
| `MIN_PORTFOLIO_BALANCE` | Min balance to include position | `1.0` |
| `INCLUDE_PORTFOLIO_IN_ANALYSIS` | Analyze portfolio holdings | `true` |

## Investment Cycle Workflow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Bitget API    │────▶│  Gemini Agent   │────▶│  JSON/DynamoDB  │
│  (Market Data)  │     │   (Analyst)     │     │    (Storage)    │
└─────────────────┘     └────────▲────────┘     └────────┬────────┘
        │                        │                       │
        │                        │                       │
        │               ┌────────┴────────┐              │
        │               │  Fundamental    │              │
        │               │  Data Service   │              │
        │               │ (CoinGecko +    │              │
        │               │  Fear & Greed)  │              │
        │               └─────────────────┘              │
        │                                                │
        │               ┌─────────────────┐              │
        │               │  DeepSeek Agent │◀─────────────┘
        │               │   (Manager)     │
        │               └────────┬────────┘
        │                        │
        └───────────────────────▶│
                        ┌────────▼────────┐
                        │   Bitget API    │
                        │ (Trade Exec)    │
                        └─────────────────┘
```

### Analysis Phase
1. **Fetch Portfolio**: Get current holdings from Bitget
2. **Filter Portfolio**: Include coins with balance > `MIN_PORTFOLIO_BALANCE`
3. **Fetch Top Coins**: Get top N coins by USDT volume
4. **Deduplicate**: Merge portfolio + top coins (no duplicates)
5. **Fetch Fundamental Data**: Fear & Greed Index + CoinGecko metrics (with caching)
6. **Auto-Lookup**: Unknown tickers discovered via CoinGecko search API
7. **Analyze**: Gemini analyzes each coin (technical + fundamental)
8. **Store**: Save analyses to JSON/DynamoDB

### Decision Phase
1. **Load Analyses**: Retrieve all stored coin analyses
2. **Fetch Portfolio**: Get current holdings (filtered by min balance)
3. **Generate Decisions**: DeepSeek R1 reviews data and generates trades
4. **Execute**: Execute trades (paper mode logs, live mode places orders)

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
