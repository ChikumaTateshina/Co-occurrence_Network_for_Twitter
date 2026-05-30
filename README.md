# Co-occurrence_Network_for_Twitter
Twitterデータアーカイブをベースとした共起ネットワーク図作成システム

Twitter アーカイブ（`tweets.js`）から形態素解析で名詞を抽出し、単語間の共起関係を Jaccard 係数で重み付けした共起ネットワーク図を生成する Python ツールです。名刺サイズ（91:55）の高解像度 PNG として出力します。

---

## 特徴

- **全ツイート対象** — リツイートを含む `full_text` をすべて解析
- **形態素解析** — MeCab（優先）または Janome（フォールバック）で名詞を基本形で抽出
- **Jaccard 係数** — 共起頻度をノード出現数で正規化し、語の出現頻度の偏りを補正
- **密集度グラデーションレイアウト** — 密集エリアほど反発力を強める独自 force-directed アルゴリズム（numpy のみで実装、scipy 不要）
- **ハブ強調表示** — 接続数と出現頻度の複合スコアでノードサイズ・フォントサイズを決定し、ハブ構造を視覚化
- **コミュニティ色分け** — scipy が使える場合は `greedy_modularity_communities`、なければ `label_propagation_communities` で自動切替
- **名刺比率出力** — 横 18.2 × 縦 11.0 インチ（= 91:55）、300 DPI の PNG

---

## 出力サンプル

<img width="4291" height="3085" alt="twitter_cooccurrence_network_edge300" src="https://github.com/user-attachments/assets/8248fdb5-11d3-420a-b2fb-292a0587bac3" />

作者のTwitterアカウントより作成



実行時コンソール表示例
```
ツイートデータを読み込んでいます...
読み込みツイート数:  3842件

共起ネットワークを解析中...
  読み込み:             3842件
    うち RT:             982件
    うちオリジナル:     2860件
  名詞なし / 空白:       143件
  名詞 1 語のみ:         214件  ← 共起ペア生成不可
  共起解析対象:         3485件  ← グラフへ寄与
  語彙総数:              1204語
  閾値 (3 回以上):        387語
  ブリッジエッジ:           8本 (12 → 1 コンポーネント)
  グラフ:                 142ノード / 338エッジ

ネットワーク図を描画中...
ネットワーク図を twitter_cooccurrence_network.png として保存しました。
```

---

## 必要環境

| 項目 | バージョン |
|------|-----------|
| Python | 3.8 以上 |
| numpy | 1.20 以上 |
| matplotlib | 3.5 以上 |
| japanize-matplotlib | 1.1 以上 |
| networkx | 2.6 以上 |
| janome | 0.4 以上 |

**任意（推奨）**

| 項目 | 用途 |
|------|------|
| mecab-python3 | Janome より高精度な形態素解析 |
| scipy | greedy modularity によるコミュニティ検出（なくても動作） |

---

## インストール

### 1. 依存パッケージのインストール

```bash
pip install numpy matplotlib japanize-matplotlib networkx janome
# 任意
pip install mecab-python3 scipy
```

### 2. MeCab バイナリ（Windows のみ・任意）

Windows で MeCab を使用する場合、Python パッケージに加えてバイナリのインストールが必要です。

1. [MeCab リリースページ](https://github.com/ikegami-yukino/mecab/releases) から最新版をダウンロード
2. インストーラを実行（辞書は UTF-8 を選択）
3. `pip install mecab-python3`

macOS / Linux では以下でインストールできます。

```bash
# macOS
brew install mecab mecab-ipadic
pip install mecab-python3

# Ubuntu / Debian
sudo apt install mecab libmecab-dev mecab-ipadic-utf8
pip install mecab-python3
```

---

## 使い方

### Twitter アーカイブの取得

1. Twitter/X の設定 → 「アカウント」→「データのアーカイブをリクエスト」
2. ダウンロードした ZIP を展開し、`data/tweets.js` を取り出す

### 実行

`tweets.js` をスクリプトと同じディレクトリに置いて実行します。

```bash
python Co-OccurrenceNetwork.py
```

または、ファイルパスを直接指定する場合はスクリプト末尾の `FILE_PATH` を変更してください。

```python
FILE_PATH = "path/to/your/tweets.js"
```

### 出力

`twitter_cooccurrence_network.png` が生成されます（名刺サイズ比率・300 DPI）。

---

## パラメータ一覧

### `build_graph()`

| パラメータ | デフォルト | 説明 |
|-----------|-----------|------|
| `min_appearance` | `3` | ノードとして含める単語の最低出現回数 |
| `top_n_edges` | `300` | Jaccard 上位何本のエッジを描画するか（デフォルトは300） |
| `min_cooccurrence` | `3` | エッジとして含める最低共起回数（この値**以下**は除外） |

### `visualize()`

| パラメータ | デフォルト | 説明 |
|-----------|-----------|------|
| `output_path` | `"twitter_cooccurrence_network.png"` | 出力ファイルパス |
| `fig_size` | `(18.2, 11.0)` | 図のサイズ（インチ）。名刺比率 91:55 |
| `dpi` | `300` | 解像度 |
| `layout_k` | `0.5` | ノード間反発係数の基準値（大きいほど疎） |
| `layout_seed` | `42` | レイアウトの乱数シード |

### `TweetCooccurrenceNetwork()`

| パラメータ | デフォルト | 説明 |
|-----------|-----------|------|
| `file_path` | — | `tweets.js` へのパス |
| `stop_words` | 組み込みリスト | 解析から除外する単語セット（`frozenset[str]`） |
| `use_mecab` | `True` | `False` にすると Janome を強制使用 |

---

## カスタマイズ

### ストップワードの追加

```python
my_stop = frozenset({"自分", "今日", "感じ"}) | _DEFAULT_STOP_WORDS

analyzer = TweetCooccurrenceNetwork("tweets.js", stop_words=my_stop)
```

### グラフオブジェクトの再利用

`build_graph()` と `visualize()` は独立しているため、グラフを一度構築して複数回描画できます。

```python
analyzer = TweetCooccurrenceNetwork("tweets.js")
tweets = analyzer.load_tweets()
G, word_counts = analyzer.build_graph(tweets, min_appearance=5, top_n_edges=200)

# 異なる出力パスで複数保存
analyzer.visualize(G, word_counts, output_path="network_a.png", layout_seed=42)
analyzer.visualize(G, word_counts, output_path="network_b.png", layout_seed=123)
```

---

## 技術的な解説

### Jaccard 係数による共起重み

ツイート内で同時に出現した単語ペアの共起数を、それぞれの出現ツイート数で正規化します。

```
Jaccard(A, B) = |A ∩ B| / |A ∪ B|
             = 共起ツイート数 / (Aの出現数 + Bの出現数 - 共起数)
```

### 密集度グラデーションレイアウト

標準の Fruchterman-Reingold レイアウトを初期配置とし、その後 60 ステップの refinement を実行します。各ノードの局所密度（半径 `base_k × 2.5` 以内のノード数）に応じて反発係数を 1〜3 倍にスケールします。密集クラスタでは強い反発で内部構造が展開され、疎な領域では弱い反発で凝集が保たれます。

### コミュニティ検出

- **scipy あり**: `greedy_modularity_communities(resolution=0.7)` — モジュラリティ最大化
- **scipy なし**: `label_propagation_communities` — ラベル伝播法（NetworkX 組み込み）

いずれも 2 ノード以下の孤立コミュニティは最大コミュニティへ統合されます。

---

## ファイル構成

```
.
├── Co-OccurrenceNetwork.py   # メインスクリプト
├── tweets.js                 # Twitter アーカイブ（別途取得が必要）
└── twitter_cooccurrence_network.png  # 生成される出力
```

---

## ライセンス

MIT License

---

## 動作確認環境

| 環境 | バージョン |
|------|-----------|
| Windows 11 | 23H2 |
| Python | 3.11 |
| numpy | 2.x |
| networkx | 3.x |
| matplotlib | 3.8 |
