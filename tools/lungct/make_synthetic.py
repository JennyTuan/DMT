"""Generate explicitly synthetic geometry test data, never an AI demonstration."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'/'lungct'))
from helpers import make_ct

parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,default=ROOT/'data'/'lungct-demo')
args=parser.parse_args()
if args.output.exists() and any(args.output.iterdir()):raise SystemExit('目标非空；为避免 UID 冲突，选择新目录')
study,_=make_ct(args.output/'thin')
make_ct(args.output/'localizer',study=study,count=2,localizer=True)
print('已生成合成体模；导入时来源代号必须填写 SYNTHETIC。不构成真实推理证据。')
