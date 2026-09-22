import sys; sys.path.insert(0,'.')
import pandas as pd, numpy as np
from lubot import load_mt5_csv
pd.set_option('display.width',250); pd.set_option('display.max_rows',300)
m1=load_mt5_csv('data/xauusd_m1.csv')['2025-08-01':]
t=pd.read_csv('study_results/v13_diag/trades_enriched2.csv',parse_dates=['entry_time','close_time','selected_time'])
d=m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
d['rng']=d.high-d.low; d['gap']=(d.open-d.close.shift()); d['gap_abs']=d.gap.abs()
d['rng20']=d.rng.rolling(20).mean().shift()
d['rng_ratio']=d.rng/d.rng20; d['gap_ratio']=d.gap_abs/d.rng20
d['body_eff']=(d.close-d.open).abs()/d.rng
t['day']=t.entry_time.dt.normalize()
day=t.groupby('day').agg(n=('key','size'),R=('r_net','sum'),stops=('outcome',lambda s:(s=='sl').sum()),buys=('side',lambda s:(s=='buy').sum()),sells=('side',lambda s:(s=='sell').sum()))
day=day.join(d[['rng','rng_ratio','gap','gap_ratio','body_eff']])
day['month']=day.index.strftime('%Y-%m')
print('April days:'); print(day[day.month=='2026-04'].round(2).to_string())
print('\nSep25 days:'); print(day[day.month=='2025-09'].round(2).to_string())
print('\nSpearman day features vs day R (all days with trades):')
for c in ('rng_ratio','gap_ratio','body_eff','n'):
    print(f'  {c}: {day[c].corr(day.R,method="spearman"):+.2f}')
day['b']=pd.cut(day.gap_ratio,[-1,0.05,0.1,0.2,9],labels=['<0.05','0.05-0.1','0.1-0.2','>0.2'])
print('\nday R by gap ratio:'); print(day.groupby('b',observed=True).agg(days=('n','size'),n=('n','sum'),R=('R','sum'),weak_R=('R',lambda s: s[day.loc[s.index,'month'].isin(['2026-04','2025-09'])].sum())).round(2))
day['b']=pd.cut(day.body_eff,[-1,0.2,0.4,0.6,1.1],labels=['<0.2','0.2-0.4','0.4-0.6','>0.6'])
print('\nday R by body efficiency (hindsight!):'); print(day.groupby('b',observed=True).agg(days=('n','size'),n=('n','sum'),R=('R','sum')).round(2))
# both-sides-stopped days
bs=day[(day.stops>=2)]
print('\ndays with >=2 stops:', len(bs), 'R', bs.R.sum().round(1)); print(bs.groupby('month').agg(days=('n','size'),R=('R','sum')).round(1).T.to_string())
# whipsaw: trade entered within X hours after a stop of the OPPOSITE side
t=t.sort_values('entry_time')
sl=t[t.outcome=='sl'][['close_time','side']].sort_values('close_time')
def last_stop(row, same):
    prev=sl[(sl.close_time<row.entry_time)&((sl.side==row.side)==same)]
    if not len(prev): return np.nan
    return (row.entry_time-prev.close_time.iloc[-1]).total_seconds()/3600
t['h_since_opp_stop']=t.apply(lambda r: last_stop(r,False),axis=1)
t['h_since_same_stop']=t.apply(lambda r: last_stop(r,True),axis=1)
for col in ('h_since_opp_stop','h_since_same_stop'):
    t['b']=pd.cut(t[col],[-1,2,6,24,72,1e9],labels=['<2h','2-6h','6-24h','1-3d','>3d'])
    print(f'\n== {col} ==')
    print(t.groupby('b',observed=True).agg(n=('key','size'),R=('r_net','sum'),win=('net',lambda s:round((s>0).mean()*100,1)),sl=('outcome',lambda s:round((s=='sl').mean()*100,1)),weak_n=('weak','sum'),weak_R=('r_net',lambda s: round(s[t.loc[s.index,'weak']].sum(),2)),OOS_R=('r_net',lambda s: round(s[t.loc[s.index,'close_time']>='2026-03-01'].sum(),2))).round(2))
t.to_csv('study_results/v13_diag/trades_enriched2.csv',index=False)
day.to_csv('study_results/v13_diag/days.csv')
