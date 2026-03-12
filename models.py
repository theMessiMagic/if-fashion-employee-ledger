from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import date, timedelta

engine = create_engine('sqlite:///factory_final.db', connect_args={'timeout': 15})
Session = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()

class Labour(Base):
    __tablename__ = 'labours'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    group = Column(String) 
    home_mc = Column(String)
    wage_rate = Column(Integer, default=0) 
    last_increment_month = Column(String, default="") # NEW FEATURE: Tracks monthly increment

class DailyEntry(Base):
    __tablename__ = 'entries'
    id = Column(Integer, primary_key=True)
    labour_id = Column(Integer)
    day_number = Column(Integer)
    day_name = Column(String)
    month_year = Column(String)
    shift = Column(String)
    mc_no = Column(String)
    stitch = Column(Integer, default=0)
    duty = Column(String, default="")
    advance = Column(Integer, default=0)
    hours = Column(String, default="FULL")
    manual_shift = Column(Integer, default=0)

Base.metadata.create_all(engine)

def get_mirrored_shift(group, d_num, m_y):
    month, year = map(int, m_y.split('-'))
    d_obj = date(year, month, d_num)
    
    first_mon = date(year, month, 1)
    while first_mon.weekday() != 0: 
        first_mon += timedelta(days=1)
    
    days_from_mon = (d_obj - first_mon).days
    week_index = days_from_mon // 7
    if d_obj < first_mon:
        week_index = -1

    if week_index % 2 == 0:
        week_shift = "Night" if group == 'A' else "Day"
    else:
        week_shift = "Day" if group == 'A' else "Night"

    if d_obj.strftime("%a") == "Sun":
        monday_of_this_week = d_obj + timedelta(days=1)
        mon_week_index = (monday_of_this_week - first_mon).days // 7
        if monday_of_this_week < first_mon: mon_week_index = -1
        
        if mon_week_index % 2 == 0:
            mon_shift = "Night" if group == 'A' else "Day"
        else:
            mon_shift = "Day" if group == 'A' else "Night"

        if mon_shift == "Day":
            return "CHANGE"
        else:
            return "Night"

    return week_shift