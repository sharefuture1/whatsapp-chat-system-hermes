# 共享语料同步方案

## 目标

LaoTalk 和 WhatsApp 两个系统共享翻译知识，让 AI 翻译质量持续提升。

- LaoTalk：用户量大、语料质量高（中文 → 老挝语为主）
- WhatsApp：真实口语场景（老挝语/泰语 → 中文为主）

两者互补，形成翻译质量提升的正向循环。

## 数据流向

```
WhatsApp 用户对话
      ↓ 翻译请求
  AI 翻译（MiniMax）
      ↓ 翻译结果 + 纠正
  review_translations.py 复习工具
      ↓ 用户纠正后自动
  POST /api/corpus/push
      ↓
  LaoTalk shared_corpus/pending/
      ↓ 管理员审核后
  shared_corpus/approved/
      ↓
  phrase_dict.json（每小时同步）
      ↓
  WhatsApp Rewriter AI prompt 注入
      ↓
  提升 WhatsApp 翻译准确度
```

## 目录结构

```
/var/www/laotalk-beta/backend/shared_corpus/
├── phrase_dict.json        # 所有 approved 语料的合并词典（自动生成）
├── approved/
│   ├── lo_zh/              # 老挝语→中文语料
│   │   └── lo_zh.jsonl
│   └── th_zh/              # 泰语→中文语料
│       └── th_zh.jsonl
└── pending/                # 待审核语料（WhatsApp 纠正后写入）
    ├── lo_zh.jsonl
    └── th_zh.jsonl
```

## 现有语料

| 来源 | 数量 | 语言方向 |
|------|------|---------|
| LaoTalk 翻译历史导出 | 1,831 条 | lo→zh / th→zh |
| LaoTalk 内部 packs | ~1,924 条 | lo→zh |

## 接口

### POST /api/corpus/push（供 WhatsApp 写入）
```json
// Header: X-Corpus-Secret: <LT_CORPUS_SECRET>
// Body:
{
  "source_lang": "lo",
  "src": "...",
  "tgt": "...",
  "corrected_by": "human",
  "source": "whatsapp",
  "user_id": "...",
  "created_at": 1752200000
}
// Response: {"ok": true, "id": "wa_..."}
```

### GET /api/corpus/dict
```json
// Response: {"dict": {"老挝语": "中文", ...}, "count": 1831}
```

### GET /api/corpus/stats
```json
// Response: {"approved": 1924, "lo_zh": 44, "th_zh": 1, "pending": 0, "phrase_dict": 1831}
```

## 导出脚本

```bash
# 导出 LaoTalk 翻译历史为语料
cd /var/www/laotalk-beta/backend
python export_corpus.py [天数]

# 例如导出最近 365 天：
python export_corpus.py 365
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LT_CORPUS_SECRET` | corpus/push 接口认证密钥 | （空） |

## 安全说明

`/api/corpus/push` 接口默认无需密钥（内网服务）。如需开启，在 `laotalk-backend.env` 中设置 `LT_CORPUS_SECRET`，WhatsApp 端通过环境变量 `LT_CORPUS_SECRET` 传递相同值。

## 维护命令

```bash
# 查看语料统计
curl http://localhost:3020/api/corpus/stats

# 手动触发导出（从 DB 历史导出到 approved/）
cd /var/www/laotalk-beta/backend
python export_corpus.py 365

# 重启服务使代码生效
sudo systemctl restart laotalk-backend
```


## WhatsApp 侧实现

### 翻译复习工具



纠正后自动 POST 到 LaoTalk 。

### 短语词典加载

 类在翻译时自动加载 ，向 AI prompt 注入最多 200 条短语参照。

词典路径通过环境变量配置：


### 定时同步

每小时自动从 LaoTalk 拉取最新 phrase_dict.json：

┌─────────────────────────────────────────────────────────────────────────┐
│                         Scheduled Jobs                                  │
└─────────────────────────────────────────────────────────────────────────┘

  d15290be46bd [active]
    Name:      laotalk-corpus-sync
    Schedule:  0 * * * *
    Repeat:    ∞
    Next run:  2026-07-11T09:00:00+00:00
    Deliver:   origin

[sync] 从 http://localhost:3020/api/corpus/dict 拉取词典 → /var/www/laotalk-beta/backend/shared_corpus/phrase_dict.json
[sync] 旧词典: 1831 条 (hash=a506671ea822)
[sync] 新词典: 1831 条 (hash=a506671ea822)
[sync] 词典无变化，跳过写入

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
|  | LaoTalk corpus/dict 接口 |  |
|  | 本地写入路径 |  |
|  | corpus/push 认证（可选） | （空） |

### 测试验证
