import pandas as pd
import matplotlib.pyplot as plt
import ta
from itertools import combinations
import optuna


# # load training data
# def load_train(file):
#     file_mapping = {
#         "A1": "data/aapl_project_1m_train.csv",
#         "A5": "data/aapl_project_train.csv",
#         "B1": "data/btc_project_1m_train.csv",
#         "B5": "data/btc_project_train.csv",
#     }
#     file_name = file_mapping.get(file)
#     if not file_name:
#         raise ValueError("File not found.")
#     data = pd.read_csv(file_name).dropna()
#     return data


class TechnicalIndicators:
    def __init__(self, data):
        self.data = data
    def calculate_rsi(self, window):
        self.data["RSI"] = ta.momentum.RSIIndicator(close=self.data['Close'], window=window).rsi()
    def calculate_boll(self, window, std):
        bollinger = ta.volatility.BollingerBands(close=self.data['Close'], window=window, window_dev=std)
        self.data['Bollinger_H'] = bollinger.bollinger_hband()
        self.data['Bollinger_L'] = bollinger.bollinger_lband()
        self.data['Bollinger_M'] = bollinger.bollinger_mavg()

    def calculate_macd(self, window_slow, window_fast, window_sign):
        macd = ta.trend.MACD(close=self.data['Close'], window_slow=window_slow, window_fast=window_fast,
                             window_sign=window_sign)
        self.data['MACD'] = macd.macd()
        self.data['MACD_Signal'] = macd.macd_signal()

    def calculate_stochastic(self, window, smooth_window):
        stochastic = ta.momentum.StochasticOscillator(close=self.data['Close'], high=self.data['High'],
                                                      low=self.data['Low'], window=window, smooth_window=smooth_window)
        self.data['Stoch'] = stochastic.stoch()

    def calculate_sma(self, window):
        self.data['SMA'] = ta.trend.SMAIndicator(close=self.data['Close'], window=window).sma_indicator()

class Backtest:
    def __init__(self, data, strategy, capital = 1_000_000, com = 0.00125, max_active_ops = 1_000):
        self.data = data
        self.strategy = strategy
        self.capital = capital
        self.initial_capital = capital
        self.com = com
        self.max_active_operations = max_active_ops
        self.portfolio_value = [capital]
        self.active_positions = []

    def generate_signals(self):
        if "RSI" in self.strategy.keys():
            rsi_ta = ta.momentum.RSIIndicator(close=self.data['Close'], window=self.strategy["RSI"]["window"])
            self.data['RSI'] = rsi_ta.rsi()
            self.data['BUY_SIGNAL'] = self.data['RSI'] < self.strategy["RSI"]["lower_threshold"]

        if "Bollinger" in self.strategy.keys():
            bollinger_ta = ta.volatility.BollingerBands(close=self.data['Close'],
                                                        window=self.strategy["Bollinger"]["window"],
                                                        window_dev=self.strategy["Bollinger"]["std"])
            self.data['Bollinger_H'] = bollinger_ta.bollinger_hband()
            self.data['Bollinger_L'] = bollinger_ta.bollinger_lband()
            self.data['Bollinger_M'] = bollinger_ta.bollinger_mavg()
            self.data['BUY_SIGNAL'] &= bollinger_ta.bollinger_lband_indicator()

        if "MACD" in self.strategy.keys():
            macd_ta = ta.trend.MACD(close=self.data['Close'], window_slow=self.strategy["MACD"]["window_slow"],
                                    window_fast=self.strategy["MACD"]["window_fast"],
                                    window_sign=self.strategy["MACD"]["window_sign"])
            self.data['MACD'] = macd_ta.macd()
            self.data['MACD_Signal'] = macd_ta.macd_signal()
            self.data['BUY_SIGNAL'] &= self.data['MACD'] > self.data['MACD_Signal']

        if "Stoch" in self.strategy.keys():
            stoch_ta = ta.momentum.StochasticOscillator(close=self.data['Close'], high=self.data['High'],
                                                        low=self.data['Low'], window=self.strategy["Stoch"]["window"],
                                                        smooth_window=self.strategy["Stoch"]["smooth_window"])
            self.data['Stoch'] = stoch_ta.stoch()
            self.data['BUY_SIGNAL'] &= self.data['Stoch'] < self.strategy["Stoch"]["threshold"]

        if "SMA" in self.strategy.keys():
            sma_ta = ta.trend.SMAIndicator(close=self.data['Close'], window=self.strategy["SMA"]["window"])
            self.data['SMA'] = sma_ta.sma_indicator()
            self.data['BUY_SIGNAL'] &= self.data['Close'] > self.data['SMA']

    def run_backtest(self):
        self.generate_signals()

        for i, row in self.data.iterrows():
            active_pos_copy = self.active_positions.copy()
            for pos in active_pos_copy:
                if pos["type"] == "LONG":
                    if row['Close'] < pos["stop_loss"]:
                        self.capital += row['Close'] * pos["n_shares"] * (1 - self.com)
                        self.active_positions.remove(pos)
                    if row['Close'] > pos["take_profit"]:
                        self.capital += row['Close'] * pos["n_shares"] * (1 - self.com)
                        self.active_positions.remove(pos)
                elif pos["type"] == "SHORT":
                    if row['Close'] > pos["stop_loss"]:
                        self.capital -= row['Close'] * pos["n_shares"] * (1 + self.com)
                        self.active_positions.remove(pos)
                    if row['Close'] < pos["take_profit"]:
                        self.capital -= row['Close'] * pos["n_shares"] * (1 + self.com)
                        self.active_positions.remove(pos)

            if row['BUY_SIGNAL'] and len(self.active_positions) < self.max_active_operations:
                if self.capital > row['Close'] * (1 + self.com) * self.strategy["n_shares"]:
                    self.capital -= row['Close'] * (1 + self.com) * self.strategy["n_shares"]
                    self.active_positions.append({
                        "type": "LONG",
                        "bought_at": row['Close'],
                        "n_shares": self.strategy["n_shares"],
                        "stop_loss": row['Close'] * (1 - self.strategy["stop_loss"]),
                        "take_profit": row['Close'] * (1 + self.strategy["take_profit"])
                    })
            if row['SELL_SIGNAL'] and len(self.active_positions) < self.max_active_operations:
                if self.capital > row['Close'] * (1 + self.com) * self.strategy["n_shares"]:
                    self.capital -= row['Close'] * (1 + self.com) * self.strategy["n_shares"]
                    self.active_positions.append({
                        "type": "SHORT",
                        "sold_at": row['Close'],
                        "n_shares": self.strategy["n_shares"],
                        "stop_loss": row['Close'] * (1 + self.strategy["stop_loss"]),
                        "take_profit": row['Close'] * (1 - self.strategy["take_profit"])
                    })

            positions_value = sum(
                pos["n_shares"] * (row['Close'] if pos["type"] == "LONG" else (2 * pos["sold_at"] - row['Close'])) for
                pos in self.active_positions)
            self.portfolio_value.append(self.capital + positions_value)

        active_pos_copy = self.active_positions.copy()
        for pos in active_pos_copy:
            if pos["type"] == "LONG":
                self.capital += row['Close'] * pos["n_shares"] * (1 - self.com)
            elif pos["type"] == "SHORT":
                self.capital -= row['Close'] * pos["n_shares"] * (1 + self.com)
            self.active_positions.remove(pos)

        self.portfolio_value.append(self.capital)
        return self.portfolio_value[-1]

    def plot_results(self):
        capital_benchmark = self.initial_capital
        shares_to_buy = capital_benchmark // (self.data['Close'].values[0] * (1 + self.com))
        capital_benchmark -= shares_to_buy * self.data['Close'].values[0] * (1 + self.com)
        portfolio_value_benchmark = (shares_to_buy * self.data['Close']) + capital_benchmark

        plt.figure(figsize=(12, 6))
        plt.plot(self.portfolio_value, label="Active Strategy")
        plt.plot(portfolio_value_benchmark, label="Buy and Hold Benchmark")
        plt.legend()
        plt.title(
            f"Active Strategy: {(self.portfolio_value[-1] / self.initial_capital - 1) * 100:.2f}% vs. Buy and Hold: {(portfolio_value_benchmark.values[-1] / self.initial_capital - 1) * 100:.2f}%")
        plt.show()

# do combinations of indicators
class StrategyOptimization:
    def __init__(self, data):
        self.data = data
        self.indicator_combinations = self.generate_combinations()

    def generate_combinations(self):
        indicators = ["RSI","Bollinger","MACD","Stoch","SMA"]
        all_combo = []

        for i in range(1, len(indicators) + 1):
            all_combo.extend(combinations(indicators, i))

        all_combo = [list(combo) for combo in all_combo]
        return all_combo



        # for combination in combinations_of_indicators:
        #     active_indicators = list(combination)
        #     strategy_value = execute_trades(data, active_indicators, best_combination, cash)
        #     result = strategy_value[-1]
        #
        #     if result > best_result:
        #         best_result = result
        #         best_combination = combination
        #
        # return best_combination, best_result




    # optimize parameters for indicators
    # def optimize_parameters(data, indicators_list, n_trials=100, initial_cash=1_000_000):

    def objective(self, data, trial):
        strategy = {}
        if "RSI" in self.indicator_combinations:
            strategy["RSI"] = {
                "window": self.suggest_int("rsi_window", 5, 50),
                "lower_threshold": self.suggest_int("rsi_lower_threshold", 10, 30)
            }
        if "Bollinger" in self.indicator_combinations:
            strategy["Bollinger"] = {
                "window": self.suggest_int("bollinger_window", 5, 50),
                "std": self.suggest_float("bollinger_std", 1.5, 3.5)
            }
        if "MACD" in self.indicator_combinations:
            strategy["MACD"] = {
                "window_slow": self.suggest_int("macd_window_slow", 20, 50),
                "window_fast": self.suggest_int("macd_window_fast", 5, 20),
                "window_sign": self.suggest_int("macd_window_sign", 5, 20)
            }
        if "Stoch" in self.indicator_combinations:
            strategy["Stoch"] = {
                "window": self.suggest_int("stoch_window", 5, 50),
                "smooth_window": self.suggest_int("stoch_smooth_window", 3, 10),
                "threshold": self.suggest_float("stoch_threshold", 0.2, 0.8)
            }
        if "SMA" in self.indicator_combinations:
            strategy["SMA"] = {
                "window": self.suggest_int("sma_window", 5, 50)
            }
        strategy["n_shares"] = self.suggest_int("n_shares", 50, 150)
        strategy["stop_loss"] = self.suggest_float("stop_loss", 0.05, 0.15)
        strategy["take_profit"] = self.suggest_float("take_profit", 0.05, 0.15)

        backtest = Backtest(self.data, strategy)
        portfolio_value = backtest.run_backtest()
        return portfolio_value[-1]

    def optimize(self):
        study = optuna.create_study(direction='maximize')
        study.optimize(self.objective, n_trials=50)
        return study.best_params

#load training data
train_data = {
"A1": "aapl_project_1m_train.csv",
    "A5": "aapl_project_train.csv",
    "B1": "btc_project_1m_train.csv",
    "B5": "btc_project_train.csv"
}
test_data = {
    "A1T": "aapl_project_1m_test.csv",
    "A5T": "aapl_project_test.csv",
    "B1T": "btc_project_1m_test.csv",
    "B5T": "btc_project_test.csv"
}

# Example usage:
data = pd.read_csv(train_data["A1"]).dropna()
ti = TechnicalIndicators(data)
ti.calculate_rsi(window=14)
ti.calculate_boll(window=20, std=2)
ti.calculate_macd(window_slow=26, window_fast=12, window_sign=9)
ti.calculate_stochastic(window=14, smooth_window=3)
ti.calculate_sma(window=30)
            # strategies = {"RSI": {"window": rsi_window, "lower_threshold": rsi_lower_threshold},
            #          "Bollinger": {"window": boll_window, "std": std_boll},
            #          "MACD": {"slow": MACD_slow, "fast": MACD_fast, "sign": MACD_sign},
            #          "Stoch": {"window": stoch_window, "smooth": stoch_smooth, "threshold": stoch_threshold},
            #          "SMA": {"window": sma_window}}
strategy = {"RSI": {"window": 14, "lower_threshold": 30},
            "Bollinger": {"window": 20, "std": 2},
            "MACD": {"slow": 26, "fast": 12, "sign": 9},
            "Stoch": {"window": 14, "smooth": 3, "threshold": 0.2},
            "SMA": {"window": 30},
            "n_shares": 100,
            "stop_loss": 0.1,
            "take_profit": 0.2
        }

backtest = Backtest(data, strategy)
portfolio_value = backtest.run_backtest()
backtest.plot_results()

optimizer = StrategyOptimization(data)
best_params = optimizer.optimize()
print(best_params)
# # "window": trial.suggest_int("rsi_window", 5, 50),
#         # "lower_threshold": trial.suggest_int("rsi_lower_threshold", 10, 30)
#         # strategies["Bollinger"] = {
#         #     "window": trial.suggest_int("bollinger_window", 5, 50),
#         #     "std": trial.suggest_float("bollinger_std", 1.5, 3.5)
#         # }
#         # if "MACD" in self.indicator_combinations:
#         #     strategies["MACD"] = {
#         #         "window_slow": trial.suggest_int("macd_window_slow", 20, 50),
#         #         "window_fast": trial.suggest_int("macd_window_fast", 5, 20),
#         #         "window_sign": trial.suggest_int("macd_window_sign", 5, 20)
#         #     }
#         # if "Stoch" in self.indicator_combinations:
#
#             # indicators = {
#             #     "RSI": {"buy": rsi_buy_signal, "sell": rsi_sell_signal},
#             #     "BOL": {"buy": bol_buy_signal, "sell": bol_sell_signal},
#             #     "MACD": {"buy": macd_buy_signal, "sell": macd_sell_signal},
#             #     "STOCH": {"buy": stoch_buy_signal, "sell": stoch_sell_signal},
#             #     "SMA": {"buy": sma_buy_signal, "sell": sma_sell_signal}
#             # }
#
#             indicators = buy_sell_signals(data, indicators)
#
#             active_indicators = []
#
#             for indicator in active_indicators:
#                 if indicator == 'RSI':
#                     rsi_window = trial.suggest_int('rsi_window', 5, 30)
#                     indicators[indicator]['params'] = {'rsi_window': rsi_window}
#
#                 elif indicator == 'Bollinger':
#                     bollinger_window = trial.suggest_int('bollinger_window', 10, 50)
#                     indicators[indicator]['params'] = {'bollinger_window': bollinger_window}
#
#                 elif indicator == 'MACD':
#                     macd_fast = trial.suggest_int('macd_fast', 10, 20)
#                     macd_slow = trial.suggest_int('macd_slow', 21, 40)
#                     macd_sign = trial.suggest_int('macd_sign', 5, 15)
#                     indicators[indicator]['params'] = {'macd_fast': macd_fast, 'macd_slow': macd_slow,
#                                                        'macd_sign': macd_sign}
#
#                 elif indicator == 'Stoch':
#                     stoch_k_window = trial.suggest_int('stoch_k_window', 5, 21)
#                     stoch_d_window = trial.suggest_int('stoch_d_window', 3, 14)
#                     stoch_smoothing = trial.suggest_int('stoch_smoothing', 3, 14)
#                     indicators[indicator]['params'] = {'stoch_k_window': stoch_k_window, 'stoch_d_window': stoch_d_window,
#                                                        'stoch_smoothing': stoch_smoothing}
#
#                 elif indicator == 'SMA':
#                     short_ma_window = trial.suggest_int('short_ma_window', 5, 20)
#                     long_ma_window = trial.suggest_int('long_ma_window', 21, 50)
#                     indicators[indicator]['params'] = {'short_ma_window': short_ma_window, 'long_ma_window': long_ma_window}
#
#             # Execute strategy
#             strategy_value = execute_trades(data, active_indicators, cash=initial_cash)
#             return strategy_value[-1]
#
#
# study = optuna.create_study(direction='maximize')
#         study.optimize(objective, n_trials=n_trials)
#
#     # Get and apply best params for each indicator
#     print(f"Mejores parámetros encontrados: {study.best_params}")
#     for indicator_name in indicators.keys():
#         if study.best_params.get(indicator_name):
#             indicators[indicator_name]['params'] = study.best_params[indicator_name]
#
#     return indicators, study.best_value
#
#
# def test_strategy(data, indicators, best_combination, cash):
#     strategy_value = execute_trades(data, indicators, best_combination, cash)
#     return strategy_value
#
#
# # How we do?
# def calculate_performance(data_path, cash=1_000_000):
#     data = load_data(data_path)
#     data = calc_indicators(data)
#     data, indicators = buy_sell_signals(data)
#
#     # Optimización de parámetros con Optuna
#     indicators, best_value = optimize_parameters(data)
#
#     # Prueba de estrategia
#     strategy_value = test_strategy(data, indicators, cash)
#     plot_results(strategy_value, data)
#
#     # Calcular rendimiento pasivo
#     rend_pasivo = calculate_performance(data_path)
#     print(f"Rendimiento pasivo para {data_path}: {rend_pasivo}%")
#
#     return indicators
#
#
# def load_data(file_path):
#     data = pd.read_csv(file_path)
#     data.dropna(inplace=True)
#     return data
#
#
# def test():
#     test_file_mapping = {
#         "A1T": "data/aapl_project_1m_test.csv",
#         "A5T": "data/aapl_project_test.csv",
#         "B1T": "data/btc_project_1m_test.csv",
#         "B5T": "data/btc_project_test.csv"
#     }
#     for interval, file_path in test_file_mapping.items():
#         data = load_data(file_path)
#         data = calc_indicators(data)
#         data, indicators = buy_sell_signals(data)
#         strategy_value = execute_trades(data, list(indicators.keys()))
#         plot_results(strategy_value, data)


# def main():
#     test()
#
#
# if __name__ == "__main__":
#     main()
