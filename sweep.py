import sys
import pandas as pd
import numpy as np
import itertools
from backtesting import Backtest
from eurusd_simon_backtest import SimonEURUSDStrategy, prepare_data, BACKTEST_COMMISSION, BACKTEST_SPREAD

def main():
    try:
        data = prepare_data()
    except Exception as e:
        print(f"Error preparing data: {e}")
        return

    rr_ratio_list = [0.7, 0.9, 1.1]
    atr_buffer_list = [0.25, 0.3]
    bull_rsi_min_list = [42, 45]
    bear_rsi_max_list = [58, 60]
    pending_ttl_bars_list = [3, 4]
    max_hold_bars_list = [8, 10]
    min_5m_score_list = [2, 3]
    cooldown_bars_list = [12, 16]
    min_risk_spread_mult_list = [2.0, 2.5]

    keys = [
        'rr_ratio', 'atr_buffer', 'bull_rsi_min', 'bear_rsi_max', 
        'pending_ttl_bars', 'max_hold_bars', 'min_5m_score', 
        'cooldown_bars', 'min_risk_spread_mult'
    ]
    
    combinations = list(itertools.product(
        rr_ratio_list, atr_buffer_list, bull_rsi_min_list, bear_rsi_max_list,
        pending_ttl_bars_list, max_hold_bars_list, min_5m_score_list,
        cooldown_bars_list, min_risk_spread_mult_list
    ))

    feasible_count = 0
    top_feasible = None
    best_overall = None
    best_overall_score = -float('inf')

    # Optimization: Use a single Backtest instance and update parameters if possible, 
    # but Backtesting.py usually expects bt.run(param=val) or similar.
    # Since we want to iterate manually for custom score and feasibility check:
    
    bt = Backtest(
        data,
        SimonEURUSDStrategy,
        cash=100000,
        commission=BACKTEST_COMMISSION,
        spread=BACKTEST_SPREAD,
        exclusive_orders=False,
        finalize_trades=True,
    )

    for combo in combinations:
        params = dict(zip(keys, combo))
        params['require_daily_bias'] = True
        
        # Run backtest with these params
        stats = bt.run(**params)
        
        win_rate = stats['Win Rate [%]']
        trades = stats['# Trades']
        ret = stats['Return [%]']
        pf = stats['Profit Factor']
        if np.isnan(pf): pf = 0
        dd = stats['Max. Drawdown [%]']
        
        # Calculate score
        # score = win + 8*max(pf-1,0)+0.05*return-0.25*abs(drawdown)-0.01*max(0,trades-100)
        score = win_rate + 8 * max(pf - 1, 0) + 0.05 * ret - 0.25 * abs(dd) - 0.01 * max(0, trades - 100)
        
        current_result = {
            'win': win_rate,
            'trades': trades,
            'return': ret,
            'pf': pf,
            'dd': dd,
            'params': params,
            'score': score
        }
        
        # Best overall
        if score > best_overall_score:
            best_overall_score = score
            best_overall = current_result
            
        # Feasible: win>=60 and trades<100 and trades>=20
        if win_rate >= 60 and 20 <= trades < 100:
            feasible_count += 1
            if top_feasible is None or score > top_feasible['score']:
                top_feasible = current_result

    print(f"FEASIBLE_COUNT: {feasible_count}")
    
    if top_feasible:
        tf = top_feasible
        print(f"TOP_FEASIBLE: win={tf['win']:.2f}, trades={tf['trades']}, return={tf['return']:.5f}, pf={tf['pf']:.5f}, params={tf['params']}")
    else:
        print("TOP_FEASIBLE: None")
        
    if best_overall:
        bo = best_overall
        print(f"BEST_OVERALL: win={bo['win']:.2f}, trades={bo['trades']}, return={bo['return']:.5f}, pf={bo['pf']:.5f}, score={bo['score']:.5f}, params={bo['params']}")

if __name__ == "__main__":
    main()
