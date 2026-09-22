import sys; sys.path.insert(0,'.')
import pandas as pd, numpy as np
from lubot import load_mt5_csv
pd.set_option('display.width',250); pd.set_option('display.max_rows',300)
m1=load_mt5_csv('data/xauusd_m1.csv')['2025-07-01':]
t=pd.read_csv('study_results/v13_diag/trades_enriched2.csv',parse_dates=['entry_time','close_time','selected_time'])
t['OOS']=t.close_time>='2026-03-01'
def summ(g, extra=''):
    return pd.Series({'n':len(g),'R':round(g.r_net.sum(),2),'avgR':round(g.r_net.mean(),3),'win':round((g.net>0).mean()*100,1),'sl':round((g.outcome=='sl').mean()*100,1),
        'apr_n':int((g.month=='2026-04').sum()),'apr_R':round(g[g.month=='2026-04'].r_net.sum(),2),'sep_n':int((g.month=='2025-09').sum()),'sep_R':round(g[g.month=='2025-09'].r_net.sum(),2),
        'OOS_n':int(g.OOS.sum()),'OOS_R':round(g[g.OOS].r_net.sum(),2)})
# ---- B. location of the zone in the trailing N-day range (known at selection time: rolling high/low of the past N*1440 minutes ending at selection)
hi=m1.high; lo=m1.low
st=pd.DatetimeIndex(t.selected_time)
zone_mid=(t.zone_top+t.zone_bottom)/2
for N in (1,3,5,10):
    rh=hi.rolling(f'{N}D').max().reindex(st,method='ffill').to_numpy(); rl=lo.rolling(f'{N}D').min().reindex(st,method='ffill').to_numpy()
    loc=(zone_mid-rl)/np.maximum(rh-rl,1e-9)
    t[f'loc{N}']=loc.round(2)
    # favourable = buy low in range / sell high in range -> 0 (best) .. 1 (worst)
    t[f'adv{N}']=np.where(t.side=='buy',loc,1-loc).round(2)
    t['b']=pd.cut(t[f'adv{N}'],[-0.01,0.2,0.4,0.6,0.8,1.01],labels=['0-0.2 (edge)','0.2-0.4','0.4-0.6','0.6-0.8','0.8-1 (wrong edge)'])
    print(f'\n== zone location in the {N}-day range, 0 = favourable edge ==')
    print(t.groupby('b',observed=True).apply(summ).to_string())
# ---- A. alternative ladders estimated from mfe_r (screen only; BE stop after leg1 assumed exact entry)
def ladder_R(mfe, outcome, levels, fracs):
    fr=np.array(fracs,float); fr=fr/fr.sum(); lv=np.array(levels,float)
    out=np.zeros(len(mfe))
    for i in range(len(mfe)):
        m=mfe[i]
        if m<lv[0]:
            out[i]=-1.0 if outcome[i]=='sl' else 0.0  # never reached leg1: stopped (or BE from other reasons)
            continue
        r=0.0
        for f,l in zip(fr,lv):
            r+= f*l if m>=l else 0.0     # legs not reached exit at BE (0)
        out[i]=r
    return out
mfe=t.mfe_r.to_numpy(); oc=t.outcome.to_numpy()
ref=ladder_R(mfe,oc,[0.6,1.2,2.4,4.8],[1,1,1,1])
print('\nref ladder estimate vs actual r_net: est %.1f actual %.1f  (est ignores spread/slippage/commission)'%(ref.sum(),t.r_net.sum()))
lads={'G 0.6/1.2/2.4/4.8 x25':([0.6,1.2,2.4,4.8],[1,1,1,1]),
      'front 0.6/1.2/2.4/4.8 50/20/20/10':([0.6,1.2,2.4,4.8],[5,2,2,1]),
      'tight 0.5/1.0/1.5/2.5 x25':([0.5,1.0,1.5,2.5],[1,1,1,1]),
      'two 0.6/1.5 50/50':([0.6,1.5],[1,1]),
      'two 0.6/2.4 50/50':([0.6,2.4],[1,1]),
      'three 0.6/1.2/2.4 x33':([0.6,1.2,2.4],[1,1,1]),
      'back 0.6/1.2/2.4/4.8 10/20/30/40':([0.6,1.2,2.4,4.8],[1,2,3,4]),
      'wide 0.8/1.6/3.2/6.4 x25':([0.8,1.6,3.2,6.4],[1,1,1,1]),
      'one 1.0':([1.0],[1])}
rows=[]
for name,(lv,fr) in lads.items():
    est=ladder_R(mfe,oc,lv,fr)
    t['est']=est
    r={'ladder':name,'all':round(est.sum(),1),'OOS':round(est[t.OOS].sum(),1),'apr26':round(est[t.month=='2026-04'].sum(),1),'sep25':round(est[t.month=='2025-09'].sum(),1)}
    for reg,col,thr in (('er10<0.3','er10',0.3),('er5<0.3','er5',0.3),('vr<0.9','volratio',0.9)):
        m=t[col]<thr
        r[f'{reg}:n']=int(m.sum()); r[f'{reg}:R']=round(est[m].sum(),1); r[f'not:{reg}:R']=round(est[~m].sum(),1)
    rows.append(r)
print('\n== ladder estimates from MFE (screening) ==')
print(pd.DataFrame(rows).to_string(index=False))
# monthly estimate of front-loaded vs ref
t['est_ref']=ref; t['est_front']=ladder_R(mfe,oc,[0.6,1.2,2.4,4.8],[5,2,2,1]); t['est_two']=ladder_R(mfe,oc,[0.6,1.5],[1,1])
print('\nmonthly: ref vs front vs two-leg estimates'); print(t.groupby('month')[['est_ref','est_front','est_two']].sum().round(1).T.to_string())
t.to_csv('study_results/v13_diag/trades_enriched3.csv',index=False)
