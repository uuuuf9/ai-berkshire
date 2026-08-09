#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财报分析数据获取脚本
基于《一本书读懂财报》方法论
使用akshare获取上市公司财务数据

使用方法:
    python fetch_data.py <股票代码>
    示例: python fetch_data.py 600519  # 贵州茅台
"""

import sys
import json
import pandas as pd
from datetime import datetime, timedelta

try:
    import akshare as ak
except ImportError:
    print("正在安装akshare...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "akshare", "--break-system-packages"])
    import akshare as ak


def get_stock_code(stock_input):
    """处理股票代码输入"""
    stock_input = str(stock_input).strip()
    
    # 沪市主板: 60开头
    if stock_input.startswith('6'):
        return stock_input, 'sh'
    # 深市主板: 00开头
    elif stock_input.startswith('0'):
        return stock_input, 'sz'
    # 创业板: 30开头
    elif stock_input.startswith('30'):
        return stock_input, 'sz'
    # 科创板: 68开头
    elif stock_input.startswith('68'):
        return stock_input, 'sh'
    # 北交所: 8开头
    elif stock_input.startswith('8'):
        return stock_input, 'bj'
    else:
        return stock_input, 'sh'


def fetch_balance_sheet(stock_code, years=5):
    """获取资产负债表数据"""
    print(f"正在获取 {stock_code} 资产负债表...")
    try:
        # 获取资产负债表
        df = ak.stock_balance_sheet_by_report_em(symbol=stock_code)
        # 筛选年报数据（报告期为12月31日）
        df['REPORT_DATE'] = pd.to_datetime(df['REPORT_DATE'])
        df = df[df['REPORT_DATE'].dt.month == 12]
        # 取最近N年
        df = df.sort_values('REPORT_DATE', ascending=False).head(years)
        
        # 提取关键字段
        key_fields = {
            'REPORT_DATE': '报告日期',
            'TOTAL_ASSETS': '总资产',
            'TOTAL_LIABILITIES': '总负债',
            'TOTAL_EQUITY': '股东权益合计',
            'MONETARYFUNDS': '货币资金',
            'ACCOUNTS_RECE': '应收账款',
            'INVENTORY': '存货',
            'TOTAL_CURRENT_ASSETS': '流动资产合计',
            'TOTAL_CURRENT_LIAB': '流动负债合计',
            'FIXED_ASSET': '固定资产',
            'GOODWILL': '商誉',
            'SHORT_LOAN': '短期借款',
            'LONG_LOAN': '长期借款',
            'UNASSIGN_RPOFIT': '未分配利润'
        }
        
        result = []
        for _, row in df.iterrows():
            item = {}
            for eng, chn in key_fields.items():
                if eng in row:
                    item[chn] = float(row[eng]) if pd.notna(row[eng]) else None
                else:
                    item[chn] = None
            item['报告日期'] = row['REPORT_DATE'].strftime('%Y-%m-%d')
            result.append(item)
        
        return result
    except Exception as e:
        print(f"获取资产负债表失败: {e}")
        return []


def fetch_income_statement(stock_code, years=5):
    """获取利润表数据"""
    print(f"正在获取 {stock_code} 利润表...")
    try:
        df = ak.stock_profit_sheet_by_report_em(symbol=stock_code)
        df['REPORT_DATE'] = pd.to_datetime(df['REPORT_DATE'])
        df = df[df['REPORT_DATE'].dt.month == 12]
        df = df.sort_values('REPORT_DATE', ascending=False).head(years)
        
        key_fields = {
            'REPORT_DATE': '报告日期',
            'TOTAL_OPERATE_INCOME': '营业收入',
            'OPERATE_COST': '营业成本',
            'OPERATE_PROFIT': '营业利润',
            'TOTAL_PROFIT': '利润总额',
            'NETPROFIT': '净利润',
            'PARENT_NETPROFIT': '归母净利润',
            'SALE_EXPENSE': '销售费用',
            'MANAGE_EXPENSE': '管理费用',
            'FINANCE_EXPENSE': '财务费用',
            'OPERATE_TAX_ADD': '营业税金及附加'
        }
        
        result = []
        for _, row in df.iterrows():
            item = {}
            for eng, chn in key_fields.items():
                if eng in row:
                    item[chn] = float(row[eng]) if pd.notna(row[eng]) else None
                else:
                    item[chn] = None
            item['报告日期'] = row['REPORT_DATE'].strftime('%Y-%m-%d')
            result.append(item)
        
        return result
    except Exception as e:
        print(f"获取利润表失败: {e}")
        return []


def fetch_cashflow_statement(stock_code, years=5):
    """获取现金流量表数据"""
    print(f"正在获取 {stock_code} 现金流量表...")
    try:
        df = ak.stock_cash_flow_sheet_by_report_em(symbol=stock_code)
        df['REPORT_DATE'] = pd.to_datetime(df['REPORT_DATE'])
        df = df[df['REPORT_DATE'].dt.month == 12]
        df = df.sort_values('REPORT_DATE', ascending=False).head(years)
        
        key_fields = {
            'REPORT_DATE': '报告日期',
            'NETCASH_OPERATE': '经营活动现金流净额',
            'NETCASH_INVEST': '投资活动现金流净额',
            'NETCASH_FINANCE': '筹资活动现金流净额',
            'CCE_ADD': '现金及现金等价物净增加额',
            'SALES_SERVICES': '销售商品提供劳务收到的现金',
            'BUY_SERVICES': '购买商品接受劳务支付的现金'
        }
        
        result = []
        for _, row in df.iterrows():
            item = {}
            for eng, chn in key_fields.items():
                if eng in row:
                    item[chn] = float(row[eng]) if pd.notna(row[eng]) else None
                else:
                    item[chn] = None
            item['报告日期'] = row['REPORT_DATE'].strftime('%Y-%m-%d')
            result.append(item)
        
        return result
    except Exception as e:
        print(f"获取现金流量表失败: {e}")
        return []


def calculate_financial_ratios(bs_data, is_data, cf_data):
    """
    基于《一本书读懂财报》计算核心财务比率
    """
    ratios = []
    
    # 按日期对齐数据
    for year_idx in range(min(len(bs_data), len(is_data), len(cf_data))):
        bs = bs_data[year_idx]
        inc = is_data[year_idx]
        cf = cf_data[year_idx]
        
        ratio = {
            '年份': bs['报告日期'][:4],
        }
        
        # === 盈利能力 ===
        if inc.get('营业收入') and inc.get('营业成本'):
            ratio['毛利率'] = (inc['营业收入'] - inc['营业成本']) / inc['营业收入'] * 100
        if inc.get('净利润') and inc.get('营业收入'):
            ratio['净利率'] = inc['净利润'] / inc['营业收入'] * 100
        if inc.get('归母净利润') and bs.get('股东权益合计'):
            ratio['ROE_净资产收益率'] = inc['归母净利润'] / bs['股东权益合计'] * 100
        if inc.get('净利润') and bs.get('总资产'):
            ratio['ROA_总资产收益率'] = inc['净利润'] / bs['总资产'] * 100
        
        # === 营运能力 ===
        if year_idx < len(bs_data) - 1:
            bs_prev = bs_data[year_idx + 1]
            avg_receivable = ((bs.get('应收账款') or 0) + (bs_prev.get('应收账款') or 0)) / 2
            avg_inventory = ((bs.get('存货') or 0) + (bs_prev.get('存货') or 0)) / 2
            avg_assets = ((bs.get('总资产') or 0) + (bs_prev.get('总资产') or 0)) / 2
            
            if inc.get('营业收入') and avg_receivable > 0:
                ratio['应收账款周转率'] = inc['营业收入'] / avg_receivable
                ratio['应收账款周转天数'] = 365 / ratio['应收账款周转率']
            if inc.get('营业成本') and avg_inventory > 0:
                ratio['存货周转率'] = inc['营业成本'] / avg_inventory
                ratio['存货周转天数'] = 365 / ratio['存货周转率']
            if inc.get('营业收入') and avg_assets > 0:
                ratio['总资产周转率'] = inc['营业收入'] / avg_assets
        
        # === 偿债能力 ===
        if bs.get('流动资产合计') and bs.get('流动负债合计'):
            ratio['流动比率'] = bs['流动资产合计'] / bs['流动负债合计']
            if bs.get('存货'):
                ratio['速动比率'] = (bs['流动资产合计'] - bs['存货']) / bs['流动负债合计']
        if bs.get('货币资金') and bs.get('流动负债合计'):
            ratio['现金比率'] = bs['货币资金'] / bs['流动负债合计']
        if bs.get('总负债') and bs.get('总资产'):
            ratio['资产负债率'] = bs['总负债'] / bs['总资产'] * 100
        
        # === 现金流分析 ===
        if cf.get('经营活动现金流净额'):
            ratio['经营现金流净额'] = cf['经营活动现金流净额']
            if inc.get('净利润'):
                ratio['经营现金流/净利润'] = cf['经营活动现金流净额'] / inc['净利润'] if inc['净利润'] != 0 else None
        
        ratios.append(ratio)
    
    return ratios


def classify_cashflow_type(cfo, cfi, cff):
    """
    根据《一本书读懂财报》Part63-72判断现金流类型
    """
    cfo_pos = cfo > 0 if cfo else False
    cfi_pos = cfi > 0 if cfi else False
    cff_pos = cff > 0 if cff else False
    
    type_map = {
        (True, True, True): ("妖精型", "经营赚钱，投资赚钱，还在融资，大概率有问题"),
        (True, True, False): ("老母鸡型", "成熟稳定企业，经营赚钱，投资赚钱，分红还债"),
        (True, False, True): ("疯牛型", "快速扩张期，经营造血，大举投资，同时融资"),
        (True, False, False): ("奶牛型", "优质企业！经营造血好，同时投资扩张+还债分红"),
        (False, True, True): ("骗钱型", "警惕！经营不行，靠卖家当和融资度日"),
        (False, True, False): ("赌徒型", "经营差，卖家当去投资，高风险"),
        (False, False, True): ("大出血型", "经营投资都差，靠输血活着"),
        (False, False, False): ("死亡型", "随时可能倒闭，极度危险"),
    }
    
    key = (cfo_pos, cfi_pos, cff_pos)
    return type_map.get(key, ("未知", "无法判断"))


def main():
    if len(sys.argv) < 2:
        print("使用方法: python fetch_data.py <股票代码>")
        print("示例: python fetch_data.py 600519  # 贵州茅台")
        sys.exit(1)
    
    stock_input = sys.argv[1]
    stock_code, _ = get_stock_code(stock_input)
    
    print(f"=" * 60)
    print(f"财报分析数据获取 - {stock_code}")
    print(f"基于肖星《一本书读懂财报》方法论")
    print(f"=" * 60)
    
    # 获取三大报表
    bs_data = fetch_balance_sheet(stock_code)
    is_data = fetch_income_statement(stock_code)
    cf_data = fetch_cashflow_statement(stock_code)
    
    if not bs_data or not is_data or not cf_data:
        print("数据获取失败，请检查股票代码或网络连接")
        sys.exit(1)
    
    # 计算财务比率
    ratios = calculate_financial_ratios(bs_data, is_data, cf_data)
    
    # 输出结果
    output = {
        '股票代码': stock_code,
        '数据获取时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '资产负债表': bs_data,
        '利润表': is_data,
        '现金流量表': cf_data,
        '财务比率': ratios
    }
    
    # 判断最新一年的现金流类型
    if cf_data:
        latest_cf = cf_data[0]
        cfo_type, cfo_desc = classify_cashflow_type(
            latest_cf.get('经营活动现金流净额'),
            latest_cf.get('投资活动现金流净额'),
            latest_cf.get('筹资活动现金流净额')
        )
        output['现金流类型'] = cfo_type
        output['现金流类型说明'] = cfo_desc
    
    # 保存到JSON文件
    output_file = f'financial_data_{stock_code}_{datetime.now().strftime("%Y%m%d")}.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n数据已保存到: {output_file}")
    print(f"\n近5年财务比率摘要:")
    print("-" * 80)
    
    for r in ratios:
        year = r['年份']
        roe = r.get('ROE_净资产收益率', 'N/A')
        gross_margin = r.get('毛利率', 'N/A')
        net_margin = r.get('净利率', 'N/A')
        debt_ratio = r.get('资产负债率', 'N/A')
        cfo_np = r.get('经营现金流/净利润', 'N/A')
        
        roe_str = f"{roe:.2f}%" if isinstance(roe, (int, float)) else roe
        gm_str = f"{gross_margin:.2f}%" if isinstance(gross_margin, (int, float)) else gross_margin
        nm_str = f"{net_margin:.2f}%" if isinstance(net_margin, (int, float)) else net_margin
        dr_str = f"{debt_ratio:.2f}%" if isinstance(debt_ratio, (int, float)) else debt_ratio
        cfo_str = f"{cfo_np:.2f}" if isinstance(cfo_np, (int, float)) else cfo_np
        
        print(f"{year}年 | ROE:{roe_str:>8} | 毛利率:{gm_str:>8} | 净利率:{nm_str:>8} | 负债率:{dr_str:>8} | 现金流/利润:{cfo_str:>8}")
    
    print("-" * 80)
    print(f"最新年度现金流类型: {output.get('现金流类型', 'N/A')}")
    print(f"说明: {output.get('现金流类型说明', 'N/A')}")
    print("\n请使用此数据进行后续财报分析")


if __name__ == '__main__':
    main()
