# lann-site 服务器批处理运行说明

lann-site 不开放公网，只做批处理输出。服务器侧只跑"租户 token 读多维表格 → 清洗 → 输出 CSV"这一类无人值守任务。

## 环境
- Python 3.11+（本地用 3.14 验证过；3.11/3.12 均可）
- 依赖：见 `requirements.txt`（当前仅 `requests`）
  ```
  pip install -r requirements.txt
  ```
- 凭证：复制 `.env.example` 为 `.env` 并填入（**专用只读飞书 app**，详见该文件注释）。`.env` 已 gitignore，不进库。

## 批处理入口
```
python -m scripts.extract_base
```
- 作用：读"租赁信息表"（多维表格，租户 token）→ 输出 `data/staging/base_table.csv`
- 只读、不写飞书、不碰云文档、不需要用户 OAuth —— 符合 lann-site 只读边界
- 退出码 0 = 成功；缺凭证会报 `缺少必填配置 XXX`（不泄密钥）

## 不在服务器批处理范围（需交互，跑不了无人值守）
- `extract_focus.py` / `extract_forecasts.py`：读测算云文档，需用户 OAuth（2h 过期、要人工登录）
- 合同租金抽取（`download_file` / `ocr_contract` / 看图）：需 OAuth + OCR + 人工读图；OCR 还需系统装 tesseract

## 边界（务必遵守）
- 只读：租赁信息表、加盟商意见记录表；不写入、不删除、不改表结构、不访问无关 Base/table
- deploy key 只读（不勾 Allow write access）
- 飞书凭证用专用 app，不复用生产；密钥只存服务器 `.env`，不提交 git
