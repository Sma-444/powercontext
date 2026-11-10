PY ?= python
Q  ?=

.PHONY: help install init ingest ask serve test eval demo state clean

help:
	@echo "make install  安装依赖（powercontext[seekdb] / pypdf / pyyaml / jieba / pytest）"
	@echo "make init     建索引并导入 corpus/"
	@echo "make ask q=…  提一个问题"
	@echo "make serve    启动本地 Web 界面（默认 http://127.0.0.1:8765）"
	@echo "make test     跑单元与集成测试"
	@echo "make eval     跑标注集评测，写 records/eval/report.md"
	@echo "make demo     一条命令演示检索 + 记忆闭环"
	@echo "make state    打印资料库 / 记忆 / 复习清单"
	@echo "make clean    清掉本地数据库与运行记录（不删 corpus/）"

install:
	$(PY) -m pip install -r requirements.txt

init:
	$(PY) -m duban init

ingest:
	$(PY) -m duban ingest

ask:
	$(PY) -m duban ask "$(q)"

serve:
	$(PY) -m duban serve

test:
	$(PY) -m pytest

eval:
	$(PY) -m duban eval

demo:
	$(PY) -m duban demo

state:
	$(PY) -m duban state

clean:
	rm -rf .runtime
	rm -rf records/db records/memory records/eval
