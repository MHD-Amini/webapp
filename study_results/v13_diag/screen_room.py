import sys; sys.path.insert(0,'.')
import pandas as pd, numpy as np
from lubot import load_mt5_csv
pd.set_option('display.width',250); pd.set_option('display.max_rows',300)
m1=load_mt5_csv('data/xauusd_m1.csv')['2025-07-01':]
t=pd.read_csv('study_results/v13_diag/trades_enriched3.csv',parse_dates=['entry_time','close_time','selected_time'])
t['OOS']=t.close_time>='2026-03-01'
rng=(m1.high.resample('1D').max()-m1.low.resample('1D').min()).dropna()
adr20=rng.rolling(20).mean(); adr5=rng.rolling(5).mean()
day=pd.DatetimeIndex(t.entry_time).normalize()-pd.Timedelta(days=1)
t['adr20']=adr20.reindex(day,method='ffill').to_numpy(); t['adr5']=adr5.reindex(day,method='ffill').to_numpy()
t['room20']=(t.adr20/t.risk_usd_per_unit).round(1)   # ADR in R units
t['room5']=(t.adr5/t.risk_usd_per_unit).round(1)
def summ(g):
    return pd.Series({'n':len(g),'R':round(g.r_net.sum(),2),'avgR':round(g.r_net.mean(),3),'win':round((g.net>0).mean()*100,1),'sl':round((g.outcome=='sl').mean()*100,1),
      'reach1.2':round((g.mfe_r>=1.2).mean()*100,1),'reach2.4':round((g.mfe_r>=2.4).mean()*100,1),'reach4.8':round((g.mfe_r>=4.8).mean()*100,1),
      'apr_n':int((g.month=='2026-04').sum()),'apr_R':round(g[g.month=='2026-04'].r_net.sum(),2),'sep_n':int((g.month=='2025-09').sum()),'sep_R':round(g[g.month=='2025-09'].r_net.sum(),2),
      'OOS_n':int(g.OOS.sum()),'OOS_R':round(g[g.OOS].r_net.sum(),2)})
for col in ('room20','room5'):
    t['b']=pd.cut(t[col],[0,4,6,8,12,20,999],labels=['<4','4-6','6-8','8-12','12-20','>20'])
    print(f'\n== {col} = ADR / zone height (R units of room) ==')
    print(t.groupby('b',observed=True)[t.columns.difference(['b'])].apply(summ).to_string())
print('\nby tf x room20:'); 
t['b']=pd.cut(t.room20,[0,6,12,999],labels=['<6','6-12','>12'])
print(t.groupby(['tf','b'],observed=True)[t.columns.difference(['b','tf'])].apply(summ)[['n','R','avgR','win','reach2.4','OOS_R']].to_string())
# what ladder would fit per room bucket (MFE estimate)
def ladder_R(mfe, outcome, levels, fracs):
    fr=np.array(fracs,float); fr=fr/fr.sum(); lv=np.array(levels,float); out=np.zeros(len(mfe))
    for i,m in enumerate(mfe):
        if m<lv[0]: out[i]=-1.0 if outcome[i]=='sl' else 0.0; continue
        out[i]=sum(f*l for f,l in zip(fr,lv) if m>=l)
    return out
lads={'G':([0.6,1.2,2.4,4.8],[1,1,1,1]),'tight':([0.5,1.0,1.5,2.5],[1,1,1,1]),'mid':([0.6,1.2,1.8,3.0],[1,1,1,1]),'back':([0.6,1.2,2.4,4.8],[1,2,3,4]),'one1':([1.0],[1]),'two0.6/1.5':([0.6,1.5],[1,1])}
t['b']=pd.cut(t.room20,[0,6,12,999],labels=['<6','6-12','>12'])
rows=[]
for name,(lv,fr) in lads.items():
    est=ladder_R(t.mfe_r.to_numpy(),t.outcome.to_numpy(),lv,fr); t['est']=est
    r={'ladder':name,'all':round(est.sum(),1)}
    for b,g in t.groupby('b',observed=True): r[f'room{b}']=round(g.est.sum(),1)
    for b,g in t.groupby('tf'): r[b]=round(g.est.sum(),1)
    rows.append(r)
print('\n== ladder MFE-estimate by room bucket and by TF ==\n', pd.DataFrame(rows).to_string(index=False))
t.to_csv('study_results/v13_diag/trades_enriched3.csv',index=False)
