import sys; sys.path.insert(0,'.')
import pandas as pd, numpy as np
from lubot import load_mt5_csv
pd.set_option('display.width',250); pd.set_option('display.max_rows',300)
m1=load_mt5_csv('data/xauusd_m1.csv')['2025-08-01':]
t=pd.read_csv('study_results/v13_diag/trades.csv',parse_dates=['entry_time','close_time','selected_time'])
c=m1.close; idx=m1.index
def px(ts): return c.reindex(ts, method='ffill').to_numpy()
et=pd.DatetimeIndex(t.entry_time)
# approach velocity: signed move toward the zone over last K minutes before the fill bar, in R (zone heights) and ATR
for K in (5,15,30):
    prev=px(et-pd.Timedelta(minutes=K)); now=px(et-pd.Timedelta(minutes=1))
    mv=now-prev
    toward=np.where(t.side=='buy', -mv, mv)   # buy: price falling into the zone => positive
    t[f'appr{K}_R']=(toward/t.risk_usd_per_unit).round(2)
    t[f'appr{K}_atr']=(toward/t.atr).round(2)
t['fast_stop']=(t.outcome=='sl')&(t.hold_min<=15)
for K in (5,15,30):
    col=f'appr{K}_atr'
    t['b']=pd.cut(t[col],[-99,0,0.5,1,2,99],labels=['<=0','0-0.5','0.5-1','1-2','>2'])
    print(f'\n== approach over {K} min (ATR of TF) ==')
    print(t.groupby('b',observed=True).agg(n=('key','size'),R=('r_net','sum'),win=('net',lambda s:round((s>0).mean()*100,1)),sl=('outcome',lambda s:round((s=='sl').mean()*100,1)),fast_stop=('fast_stop','mean'),weak_n=('weak','sum'),weak_R=('r_net',lambda s: round(s[t.loc[s.index,'weak']].sum(),2)),OOS_R=('r_net',lambda s: round(s[t.loc[s.index,'close_time']>='2026-03-01'].sum(),2))).round(2))
# in R
for K in (15,):
    col=f'appr{K}_R'
    t['b']=pd.cut(t[col],[-99,0,1,2,4,99],labels=['<=0','0-1R','1-2R','2-4R','>4R'])
    print(f'\n== approach over {K} min in R ==')
    print(t.groupby('b',observed=True).agg(n=('key','size'),R=('r_net','sum'),win=('net',lambda s:round((s>0).mean()*100,1)),sl=('outcome',lambda s:round((s=='sl').mean()*100,1)),weak_R=('r_net',lambda s: round(s[t.loc[s.index,'weak']].sum(),2)),OOS_R=('r_net',lambda s: round(s[t.loc[s.index,'close_time']>='2026-03-01'].sum(),2))).round(2))
# size of the fill bar itself (M1 range in ATR) -> blow-through
h=m1.high.reindex(et).to_numpy(); l=m1.low.reindex(et).to_numpy()
t['fillbar_atr']=((h-l)/t.atr).round(2)
t['b']=pd.cut(t.fillbar_atr,[-1,0.25,0.5,1,99],labels=['<0.25','0.25-0.5','0.5-1','>1'])
print('\n== fill-bar M1 range / ATR(tf) ==')
print(t.groupby('b',observed=True).agg(n=('key','size'),R=('r_net','sum'),win=('net',lambda s:round((s>0).mean()*100,1)),sl=('outcome',lambda s:round((s=='sl').mean()*100,1)),weak_R=('r_net',lambda s: round(s[t.loc[s.index,'weak']].sum(),2)),OOS_R=('r_net',lambda s: round(s[t.loc[s.index,'close_time']>='2026-03-01'].sum(),2))).round(2))
# chop regime at entry: 5-day and 10-day efficiency ratio of D1 closes (known at entry: closed days)
d1=c.resample('1D').last().dropna()
for N in (5,10):
    er=(d1.diff(N).abs()/d1.diff().abs().rolling(N).sum())
    day=et.normalize()-pd.Timedelta(days=1)
    t[f'er{N}']=er.reindex(day,method='ffill').to_numpy().round(2)
    t['b']=pd.cut(t[f'er{N}'],[-0.01,0.2,0.4,0.6,1.01],labels=['<0.2','0.2-0.4','0.4-0.6','>0.6'])
    print(f'\n== D1 efficiency ratio {N}d at entry ==')
    print(t.groupby('b',observed=True).agg(n=('key','size'),R=('r_net','sum'),win=('net',lambda s:round((s>0).mean()*100,1)),sl=('outcome',lambda s:round((s=='sl').mean()*100,1)),reach12=('mfe_r',lambda s:round((s>=1.2).mean()*100,1)),reach24=('mfe_r',lambda s:round((s>=2.4).mean()*100,1)),weak_n=('weak','sum'),weak_R=('r_net',lambda s: round(s[t.loc[s.index,'weak']].sum(),2)),OOS_R=('r_net',lambda s: round(s[t.loc[s.index,'close_time']>='2026-03-01'].sum(),2))).round(2))
# vol ratio: 5d avg daily range / 20d
rng=(m1.high.resample('1D').max()-m1.low.resample('1D').min()).dropna()
vr=(rng.rolling(5).mean()/rng.rolling(20).mean())
day=et.normalize()-pd.Timedelta(days=1)
t['volratio']=vr.reindex(day,method='ffill').to_numpy().round(2)
t['b']=pd.cut(t.volratio,[0,0.7,0.9,1.1,1.4,9],labels=['<0.7','0.7-0.9','0.9-1.1','1.1-1.4','>1.4'])
print('\n== vol ratio 5d/20d daily range at entry ==')
print(t.groupby('b',observed=True).agg(n=('key','size'),R=('r_net','sum'),win=('net',lambda s:round((s>0).mean()*100,1)),sl=('outcome',lambda s:round((s=='sl').mean()*100,1)),reach12=('mfe_r',lambda s:round((s>=1.2).mean()*100,1)),weak_n=('weak','sum'),weak_R=('r_net',lambda s: round(s[t.loc[s.index,'weak']].sum(),2)),OOS_R=('r_net',lambda s: round(s[t.loc[s.index,'close_time']>='2026-03-01'].sum(),2))).round(2))
# stops-per-day pause: P&L of trades ENTERED after the k-th stop closed on the same server day
t=t.sort_values('entry_time'); t['day']=t.entry_time.dt.normalize()
sl=t[t.outcome=='sl'].sort_values('close_time')
for k in (1,2,3):
    after=[]
    for day,g in t.groupby('day'):
        s=sl[sl.close_time.dt.normalize()==day].close_time.sort_values().to_numpy()
        if len(s)>=k:
            cut=s[k-1]
            after.append(g[g.entry_time>cut])
    a=pd.concat(after) if after else t.iloc[0:0]
    print(f'\n== trades entered after the {k}-th stop of the day: n {len(a)} R {a.r_net.sum():+.2f} win {(a.net>0).mean()*100:.1f} | weak-month part n {a.weak.sum()} R {a[a.weak].r_net.sum():+.2f} | OOS R {a[a.close_time>="2026-03-01"].r_net.sum():+.2f}')
    print(a.groupby('month').r_net.agg(['size','sum']).round(2).T.to_string())
t.to_csv('study_results/v13_diag/trades_enriched2.csv',index=False)
