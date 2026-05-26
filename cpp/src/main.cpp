#include "quant_forge/engine.hpp"
#include "quant_forge/strategies.hpp"
#include "quant_forge/metrics.hpp"

#include <iostream>
#include <fstream>
#include <filesystem>
#include <string>
#include <string_view>
#include <cstdlib>

namespace fs = std::filesystem;

namespace {

struct CliArgs {
    std::string bars_path;
    std::string strategy_name = "momentum_ema_hysteresis";
    std::string config_path;
    std::string out_dir = "runs/latest";
};

void print_usage(const char* prog) {
    std::cerr << "QuantForge v0.1.0 — C++ Backtesting Engine\n\n"
              << "Usage: " << prog << " [options]\n\n"
              << "Options:\n"
              << "  --bars PATH      CSV file with bars (required)\n"
              << "                     Columns: symbol,timestamp,open,high,low,close,volume\n"
              << "  --strategy NAME  Strategy to run (default: momentum_ema_hysteresis)\n"
              << "                     Available: momentum_ema_hysteresis, buy_and_hold\n"
              << "  --config PATH    JSON config file (optional, uses defaults)\n"
              << "  --out DIR        Output directory (default: runs/latest)\n"
              << "  --help           Show this message\n";
}

CliArgs parse_args(int argc, char* argv[]) {
    CliArgs args;
    for (int i = 1; i < argc; ++i) {
        std::string_view arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            print_usage(argv[0]);
            std::exit(0);
        } else if (arg == "--bars" && i + 1 < argc) {
            args.bars_path = argv[++i];
        } else if (arg == "--strategy" && i + 1 < argc) {
            args.strategy_name = argv[++i];
        } else if (arg == "--config" && i + 1 < argc) {
            args.config_path = argv[++i];
        } else if (arg == "--out" && i + 1 < argc) {
            args.out_dir = argv[++i];
        } else {
            std::cerr << "Unknown option: " << arg << "\n";
            print_usage(argv[0]);
            std::exit(1);
        }
    }

    if (args.bars_path.empty()) {
        std::cerr << "Error: --bars PATH is required\n";
        print_usage(argv[0]);
        std::exit(1);
    }

    return args;
}

void write_csv_header(std::ofstream& f, const std::vector<std::string>& cols) {
    for (size_t i = 0; i < cols.size(); ++i) {
        if (i > 0) f << ",";
        f << cols[i];
    }
    f << "\n";
}

void write_trades_csv(const std::string& path, const std::vector<qf::Fill>& fills) {
    std::ofstream f(path);
    if (!f) {
        std::cerr << "Error: cannot write " << path << "\n";
        return;
    }
    write_csv_header(f, {"order_id","symbol","side","price","quantity","timestamp","commission","slippage_bps"});
    for (const auto& fill : fills) {
        f << fill.order_id << ","
          << fill.symbol << ","
          << (fill.side == qf::Side::Buy ? "Buy" : "Sell") << ","
          << fill.price << ","
          << fill.quantity << ","
          << fill.ts << ","
          << fill.commission << ","
          << fill.slippage_bps << "\n";
    }
}

void write_equity_csv(const std::string& path,
                      const std::vector<std::pair<qf::Timestamp, double>>& curve) {
    std::ofstream f(path);
    if (!f) return;
    write_csv_header(f, {"timestamp","equity"});
    for (const auto& [ts, eq] : curve) {
        f << ts << "," << eq << "\n";
    }
}

void write_metrics_json(const std::string& path, const qf::SimulationMetrics& m) {
    std::ofstream f(path);
    if (!f) return;
    f << "{\n"
      << "  \"total_return_pct\": " << m.total_return_pct << ",\n"
      << "  \"annualized_return_pct\": " << m.annualized_return_pct << ",\n"
      << "  \"sharpe_ratio\": " << m.sharpe_ratio << ",\n"
      << "  \"sortino_ratio\": " << m.sortino_ratio << ",\n"
      << "  \"max_drawdown_pct\": " << m.max_drawdown_pct << ",\n"
      << "  \"win_rate_pct\": " << m.win_rate_pct << ",\n"
      << "  \"profit_factor\": " << m.profit_factor << ",\n"
      << "  \"avg_trade_pnl\": " << m.avg_trade_pnl << ",\n"
      << "  \"total_trades\": " << m.total_trades << ",\n"
      << "  \"winning_trades\": " << m.winning_trades << ",\n"
      << "  \"losing_trades\": " << m.losing_trades << ",\n"
      << "  \"calmar_ratio\": " << m.calmar_ratio << ",\n"
      << "  \"daily_volatility_pct\": " << m.daily_volatility_pct << "\n"
      << "}\n";
}

} // anonymous namespace

int main(int argc, char* argv[]) {
    auto args = parse_args(argc, argv);

    // ── Load data ──────────────────────────────────────────────────
    std::cout << "Loading bars from " << args.bars_path << "...\n";
    qf::MarketDataStore store;
    try {
        auto bar_data = qf::parse_bars_csv(args.bars_path);
        for (auto& [symbol, bars] : bar_data) {
            store.load_bars(symbol, bars);
        }
        std::cout << "  Loaded " << bar_data.size() << " symbols\n";
        for (const auto& [sym, bars] : bar_data) {
            std::cout << "    " << sym << ": " << bars.size() << " bars\n";
        }
    } catch (const std::exception& e) {
        std::cerr << "Error loading bars: " << e.what() << "\n";
        return 1;
    }

    // ── Strategy ───────────────────────────────────────────────────
    auto symbols = store.symbols();
    if (symbols.empty()) {
        std::cerr << "Error: no symbols loaded\n";
        return 1;
    }

    std::cout << "Building strategy: " << args.strategy_name << "...\n";
    qf::Strategy strategy;
    try {
        strategy = qf::strategies::build_strategy(args.strategy_name, symbols);
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << "\n";
        return 1;
    }

    // ── Config ─────────────────────────────────────────────────────
    qf::SimulationConfig config;
    config.symbols = symbols;
    config.start_ts = store.earliest_ts();
    config.end_ts = store.latest_ts();

    std::cout << "Date range: " << config.start_ts << " → " << config.end_ts << "\n";

    // ── Run simulation ─────────────────────────────────────────────
    std::cout << "Running simulation...\n";
    qf::SimulationEngine engine(config);
    engine.load_data(std::move(store));
    engine.register_strategy(std::move(strategy));

    auto metrics = engine.run();

    // ── Compute full metrics ───────────────────────────────────────
    auto full_metrics = qf::metrics::compute_all(
        engine.equity_curve(),
        engine.fills(),
        config.initial_capital,
        config.start_ts,
        config.end_ts);

    // ── Output ─────────────────────────────────────────────────────
    fs::create_directories(args.out_dir);
    std::cout << "Writing output to " << args.out_dir << "/\n";

    write_trades_csv(args.out_dir + "/trades.csv", engine.fills());
    std::cout << "  trades.csv  (" << engine.fills().size() << " fills)\n";

    write_equity_csv(args.out_dir + "/equity.csv", engine.equity_curve());
    std::cout << "  equity.csv  (" << engine.equity_curve().size() << " points)\n";

    write_metrics_json(args.out_dir + "/metrics.json", full_metrics);

    // ── Print summary ──────────────────────────────────────────────
    std::cout << "\n═══════════════════════════════════════════\n";
    std::cout << "  Simulation Results\n";
    std::cout << "═══════════════════════════════════════════\n";
    std::cout << "  Total Return:       " << full_metrics.total_return_pct << "%\n";
    std::cout << "  Annualized Return:  " << full_metrics.annualized_return_pct << "%\n";
    std::cout << "  Sharpe Ratio:       " << full_metrics.sharpe_ratio << "\n";
    std::cout << "  Max Drawdown:       " << full_metrics.max_drawdown_pct << "%\n";
    std::cout << "  Win Rate:           " << full_metrics.win_rate_pct << "%\n";
    std::cout << "  Profit Factor:      " << full_metrics.profit_factor << "\n";
    std::cout << "  Total Trades:       " << full_metrics.total_trades << "\n";
    std::cout << "  Calmar Ratio:       " << full_metrics.calmar_ratio << "\n";
    std::cout << "  Daily Volatility:   " << full_metrics.daily_volatility_pct << "%\n";
    std::cout << "═══════════════════════════════════════════\n";
    std::cout << "  Output: " << fs::absolute(args.out_dir).string() << "/\n";

    return 0;
}
