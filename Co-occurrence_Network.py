from __future__ import annotations

import json
import re
from collections import Counter
from itertools import chain, combinations
from pathlib import Path
from typing import Optional

import numpy as np  # type: ignore[import]

# NumPy 2.0 で np.alltrue が削除されたため依存ライブラリ向けの互換シム
if not hasattr(np, "alltrue"):
    np.alltrue = np.all  # type: ignore[attr-defined]

import japanize_matplotlib  # noqa: F401 — rcParams に日本語フォントを登録
import matplotlib as mpl
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import networkx as nx
from janome.tokenizer import Tokenizer

# scipy の有無を確認（インポートせず）
import importlib.util as _ilu
_HAS_SCIPY = _ilu.find_spec("scipy") is not None
del _ilu

try:
    from networkx.algorithms.community import greedy_modularity_communities  # type: ignore[import]
    _HAS_GREEDY = _HAS_SCIPY  # greedy_modularity_communities は scipy を内部使用
except ImportError:
    _HAS_GREEDY = False

# MeCab 優先、未インストール時は Janome にフォールバック
# インストール: pip install mecab-python3
#   ※ Windows では別途 MeCab バイナリも必要
#     (https://github.com/ikegami-yukino/mecab/releases)
try:
    import MeCab as _MeCab  # type: ignore[import]
    _MECAB_AVAILABLE = True
except ImportError:
    _MeCab = None  # type: ignore[assignment]
    _MECAB_AVAILABLE = False

# NLTK による英語名詞抽出（未インストール時はスキップ）
# インストール: pip install nltk
try:
    import nltk as _nltk  # type: ignore[import]
    from nltk.tokenize import word_tokenize as _word_tokenize  # type: ignore[import]
    from nltk.tag import pos_tag as _pos_tag  # type: ignore[import]

    def _ensure_nltk_data() -> None:
        for resource, pkg in [
            ("tokenizers/punkt_tab", "punkt_tab"),
            ("tokenizers/punkt",     "punkt"),
            ("taggers/averaged_perceptron_tagger_eng", "averaged_perceptron_tagger_eng"),
            ("taggers/averaged_perceptron_tagger",     "averaged_perceptron_tagger"),
        ]:
            try:
                _nltk.data.find(resource)
                return  # 見つかれば終了
            except LookupError:
                try:
                    _nltk.download(pkg, quiet=True)
                except Exception:
                    pass

    _ensure_nltk_data()
    _NLTK_AVAILABLE = True
except ImportError:
    _nltk = None  # type: ignore[assignment]
    _word_tokenize = None  # type: ignore[assignment]
    _pos_tag = None  # type: ignore[assignment]
    _NLTK_AVAILABLE = False

# ---- 正規表現（モジュールレベルで事前コンパイル） ----
_RE_URL = re.compile(r"https?://\S+")
_RE_MENTION = re.compile(r"@\w+")
_RE_HASHTAG = re.compile(r"#\w+")
_RE_RT_PREFIX = re.compile(r"^RT\s+@\w+:\s*")
# 日本語文字（ひらがな・カタカナ・CJK漢字）の検出
_RE_JP = re.compile(r"[぀-ヿ一-鿿＀-￯]")

# ---- 定数 ----
_DEFAULT_STOP_WORDS: frozenset[str] = frozenset({
    "そう", "これ", "それ", "あれ", "どの", "どこ", "どれ",
    "もの", "こと", "とき", "よう", "ため", "ところ", "わけ", "はず",
    "みたい", "そこ", "よく", "ちょっと", "なん",
    "ツイート", "リツイート",
})
_EXCLUDED_NOUN_SUBTYPES: frozenset[str] = frozenset({"代名詞", "非自立", "特殊", "数"})

_EN_STOP_WORDS: frozenset[str] = frozenset({
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "it", "its", "they", "them", "their", "what", "which",
    "who", "whom", "this", "that", "these", "those", "am", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "shall", "should", "may", "might",
    "must", "can", "could", "a", "an", "the", "and", "but", "if", "or",
    "as", "of", "at", "by", "for", "with", "about", "into", "through",
    "to", "from", "up", "in", "out", "on", "off", "then", "here", "there",
    "when", "where", "why", "how", "all", "both", "each", "more", "most",
    "no", "not", "only", "same", "so", "than", "too", "very", "just",
    "now", "rt", "tweet", "retweet", "via", "amp",
})

# 白背景色
_BG = (1.0, 1.0, 1.0, 1.0)  # 白 RGBA

# コミュニティ色分け用パレット
# 純色比約50%（S=50-60%, L=46-58%）・原色除外・茶/灰/オリーブ除外
# 色相環を均等に分割し、各色が明確に識別できる中彩度で統一
_PALETTE = [
    "#4a9bbf",  # スカイブルー   hsl(200°, 52%, 52%)
    "#e9da65",  # コーラル       hsl(18°,  60%, 57%)
    "#35b585",  # シーフォーム   hsl(158°, 55%, 46%)
    "#9e5ec4",  # バイオレット   hsl(272°, 52%, 57%)
    "#ef730e",  # アンバー       hsl(45°,  61%, 48%)
    "#35a8a8",  # アクア         hsl(180°, 52%, 44%)
    "#c43d85",  # ラズベリー     hsl(330°, 58%, 50%)
    "#5975c4",  # ペリウィンクル hsl(225°, 52%, 56%)
    "#b540b5",  # オーキッド     hsl(300°, 54%, 48%)
    "#75b035",  # ライム         hsl(90°,  55%, 45%)
]

# 日本語フォントキーワード（Latin 系フォントを排除するためのヒント）
_JP_FONT_HINTS = ("ipa", "gothic", "mincho", "meiryo", "yu ", "noto",
                  "cjk", "hiragino", "bizud", "ms p", "ms g", "hg ")


def _detect_japanese_font() -> str:
    """
    利用可能な日本語フォント名を返す。
    japanize_matplotlib の rcParams 設定を優先し、
    日本語キーワードを含まない場合はフォント一覧から探索する。
    """
    family = mpl.rcParams.get("font.family", [])
    first = (family[0] if isinstance(family, list) and family
             else family if isinstance(family, str) else "")

    # japanize_matplotlib が日本語フォントを設定済みならそれを使用
    if first and any(h in first.lower() for h in _JP_FONT_HINTS):
        return first

    # フォント一覧から日本語対応フォントを探索（優先順）
    available = {f.name for f in fm.fontManager.ttflist}
    for name in ("IPAexGothic", "IPAPGothic", "IPAGothic",
                 "Noto Sans CJK JP", "Noto Sans JP",
                 "Yu Gothic", "Meiryo", "BIZ UDGothic",
                 "MS Gothic", "MS PGothic", "HG Gothic M"):
        if name in available:
            return name

    # 上記でも見つからない場合、japanize_matplotlib の設定をそのまま信頼
    return first or "sans-serif"


_JP_FONT = _detect_japanese_font()
# 検出したフォントを rcParams にも反映（ax.text の fontfamily 省略時にも有効）
mpl.rcParams["font.family"] = _JP_FONT


def _density_gradient_layout(
    G: nx.Graph,
    base_k: float,
    iterations: int,
    seed: int,
) -> dict:
    """
    密集度グラデーション反発力レイアウト。
    各ノードの局所密度を計算し、密集箇所では反発係数を強め（最大3倍）、
    疎な箇所では弱めて凝集を保つ。numpy の行列演算で O(n²) を高速処理する。
    """
    node_list = list(G.nodes())
    n_nodes = len(node_list)
    if n_nodes == 0:
        return {}
    if n_nodes == 1:
        return {node_list[0]: (0.0, 0.0)}

    # Phase 1: 標準 spring_layout で安定した初期配置を得る
    init_pos = nx.spring_layout(G, k=base_k, iterations=iterations, seed=seed)
    pos = np.array([init_pos[nd] for nd in node_list], dtype=float)

    # 引力計算用の隣接行列（scipy 不要の純 numpy 実装）
    node_idx = {nd: i for i, nd in enumerate(node_list)}
    adj = np.zeros((n_nodes, n_nodes), dtype=float)
    for u, v, data in G.edges(data=True):
        i, j = node_idx[u], node_idx[v]
        w = float(data.get("weight", 1.0))
        adj[i, j] = w
        adj[j, i] = w

    # Phase 2: 密度適応 refinement（クーリングスケジュール付き）
    for step in range(60):
        temp = base_k * 0.12 * (1.0 - step / 60)

        diff = pos[:, np.newaxis, :] - pos[np.newaxis, :, :]    # (n, n, 2)
        dist_sq = (diff ** 2).sum(axis=2)                        # (n, n)
        dist = np.sqrt(dist_sq)
        np.fill_diagonal(dist, np.inf)

        # 局所密度: base_k * 2.5 の半径内のノード数
        density = (dist < base_k * 2.5).sum(axis=1).astype(float)
        density_norm = density / max(float(density.max()), 1.0)  # [0, 1]

        # 密度比例の有効反発係数（疎: 1倍 ⟶ 密: 3倍）
        eff_k = base_k * (1.0 + density_norm * 2.0)             # (n,)

        # 反発力: eff_k² / dist²
        rep = (eff_k[:, np.newaxis] ** 2) / np.maximum(dist_sq, 1e-8)
        np.fill_diagonal(rep, 0.0)

        # 引力: dist² / base_k（隣接エッジのみ）
        att = (dist_sq / max(base_k, 1e-9)) * adj

        # 単位方向ベクトル
        safe_dist = np.where(np.isinf(dist), 1.0, np.maximum(dist, 1e-9))
        unit = diff / safe_dist[:, :, np.newaxis]                # (n, n, 2)

        forces = ((rep - att)[:, :, np.newaxis] * unit).sum(axis=1)  # (n, 2)

        # 最大力をクリップして発散を防ぐ
        norms = np.linalg.norm(forces, axis=1, keepdims=True)
        max_f = base_k * 2.0
        forces = np.where(norms > max_f, forces / norms * max_f, forces)

        pos += forces * temp

    return {nd: (float(pos[i, 0]), float(pos[i, 1])) for i, nd in enumerate(node_list)}


def _fallback_communities(G: nx.Graph) -> list[set]:
    """
    scipy 未インストール時のコミュニティ検出フォールバック。
    NetworkX 組み込みのラベル伝播法（scipy 不要）を使用する。
    """
    try:
        from networkx.algorithms.community import label_propagation_communities  # type: ignore[import]
        communities = list(label_propagation_communities(G))
    except Exception:
        communities = [set(G.nodes())]

    # 孤立 2 ノード以下の小コミュニティを最大コミュニティへ統合
    large = [c for c in communities if len(c) >= 3]
    small_nodes: set = set().union(*(c for c in communities if len(c) < 3))
    if small_nodes and large:
        biggest = max(large, key=len)
        communities = [c | small_nodes if c is biggest else c for c in large]

    return communities if communities else [set(G.nodes())]


class TweetCooccurrenceNetwork:
    def __init__(
        self,
        file_path: str | Path,
        stop_words: Optional[frozenset[str]] = None,
        use_mecab: bool = True,
        lang: str = "auto",
    ) -> None:
        """
        lang:
          "auto"  ツイートごとに日本語文字の有無で自動判定（デフォルト）
          "ja"    常に日本語形態素解析
          "en"    常に英語 NLTK 解析
          "both"  日英両方で抽出して合算（バイリンガルアカウント向け）
        """
        self.file_path = Path(file_path)
        self.stop_words = stop_words if stop_words is not None else _DEFAULT_STOP_WORDS

        if lang not in ("auto", "ja", "en", "both"):
            raise ValueError(f"lang は 'auto' / 'ja' / 'en' / 'both' のいずれかを指定してください: {lang!r}")
        self._lang = lang

        self._use_mecab = use_mecab and _MECAB_AVAILABLE
        if self._use_mecab:
            self._tagger = _MeCab.Tagger()
            self._tagger.parse("")  # 初回遅延を防ぐウォームアップ
            print("形態素解析エンジン (日本語): MeCab")
        else:
            self._janome = Tokenizer()
            if use_mecab and not _MECAB_AVAILABLE:
                print("形態素解析エンジン (日本語): Janome（MeCab 未インストールのためフォールバック）")
                print("  MeCab を使用する場合: pip install mecab-python3")
            else:
                print("形態素解析エンジン (日本語): Janome")

        if lang in ("en", "both", "auto"):
            if _NLTK_AVAILABLE:
                print("形態素解析エンジン (英語): NLTK")
            elif lang in ("en", "both"):
                print("警告: NLTK が未インストールのため英語抽出が無効です。")
                print("  インストール: pip install nltk")

    def load_tweets(self) -> list[str]:
        """tweets.js 内の全ツイートの full_text を返す（RT を含む）"""
        raw = self.file_path.read_text(encoding="utf-8")
        m = re.search(r"window\.YTD\.tweets\.part0\s*=\s*(.*)", raw, re.DOTALL)
        if not m:
            raise ValueError("tweets.js のフォーマット解析に失敗しました。")
        tweet_data = json.loads(m.group(1))
        return [
            text
            for entry in tweet_data
            if (text := entry.get("tweet", {}).get("full_text", ""))
        ]

    def _clean(self, text: str) -> str:
        """RT プレフィックス・URL・メンション・ハッシュタグを除去"""
        text = _RE_RT_PREFIX.sub("", text)
        text = _RE_URL.sub("", text)
        text = _RE_MENTION.sub("", text)
        return _RE_HASHTAG.sub("", text).strip()

    def _extract_nouns_mecab(self, text: str) -> list[str]:
        """MeCab で名詞を抽出し基本形（辞書形）を返す"""
        seen: set[str] = set()
        result: list[str] = []
        node = self._tagger.parseToNode(self._clean(text))
        while node:
            if not node.surface:
                node = node.next
                continue
            features = node.feature.split(",")
            if len(features) >= 7 and features[0] == "名詞":
                if features[1] not in _EXCLUDED_NOUN_SUBTYPES:
                    base = features[6] if features[6] not in ("*", "") else node.surface
                    if len(base) >= 2 and base not in self.stop_words and base not in seen:
                        seen.add(base)
                        result.append(base)
            node = node.next
        return result

    def _extract_nouns_janome(self, text: str) -> list[str]:
        """Janome で名詞を抽出し基本形（辞書形）を返す"""
        seen: set[str] = set()
        result: list[str] = []
        for token in self._janome.tokenize(self._clean(text)):
            pos = token.part_of_speech.split(",")
            if pos[0] != "名詞" or pos[1] in _EXCLUDED_NOUN_SUBTYPES:
                continue
            base = pos[6] if len(pos) > 6 and pos[6] not in ("*", "") else token.surface
            if len(base) >= 2 and base not in self.stop_words and base not in seen:
                seen.add(base)
                result.append(base)
        return result

    def _extract_nouns_english(self, text: str) -> list[str]:
        """NLTK で英語名詞（NN/NNS/NNP/NNPS）を抽出して小文字で返す"""
        if not _NLTK_AVAILABLE:
            return []
        cleaned = self._clean(text)
        if not cleaned:
            return []
        try:
            tokens = _word_tokenize(cleaned)
            tagged = _pos_tag(tokens)
        except Exception:
            return []
        seen: set[str] = set()
        result: list[str] = []
        for word, tag in tagged:
            if not tag.startswith("NN"):
                continue
            w = word.lower()
            if (len(w) >= 2
                    and w.isalpha()
                    and w not in _EN_STOP_WORDS
                    and w not in self.stop_words
                    and w not in seen):
                seen.add(w)
                result.append(w)
        return result

    def _extract_nouns_ja(self, text: str) -> list[str]:
        """日本語形態素解析エンジンで名詞を抽出する"""
        if self._use_mecab:
            return self._extract_nouns_mecab(text)
        return self._extract_nouns_janome(text)

    def _extract_nouns(self, text: str) -> list[str]:
        cleaned = self._clean(text)
        if not cleaned:
            return []

        if self._lang == "ja":
            return self._extract_nouns_ja(text)

        if self._lang == "en":
            return self._extract_nouns_english(text)

        is_japanese = bool(_RE_JP.search(cleaned))

        if self._lang == "auto":
            return self._extract_nouns_ja(text) if is_japanese else self._extract_nouns_english(text)

        # "both": 日英両方を抽出して重複除去
        ja_nouns = self._extract_nouns_ja(text) if is_japanese else []
        en_nouns = self._extract_nouns_english(text)
        seen = set(ja_nouns)
        return ja_nouns + [w for w in en_nouns if w not in seen]

    def build_graph(
        self,
        tweets: list[str],
        min_appearance: int = 5,
        top_n_edges: int = 50,
        min_cooccurrence: int = 3,
    ) -> tuple[nx.Graph, Counter]:
        """Jaccard 係数で重み付けした共起グラフを構築し解析統計を表示する"""
        word_sets = [self._extract_nouns(t) for t in tweets]

        rt_count = sum(1 for t in tweets if t.startswith("RT "))
        with_any_noun = sum(1 for w in word_sets if len(w) >= 1)
        with_pair = sum(1 for w in word_sets if len(w) >= 2)

        print(f"  読み込み:            {len(tweets):>6}件")
        print(f"    うち RT:           {rt_count:>6}件")
        print(f"    うちオリジナル:    {len(tweets) - rt_count:>6}件")
        print(f"  名詞なし / 空白:     {len(tweets) - with_any_noun:>6}件")
        print(f"  名詞 1 語のみ:       {with_any_noun - with_pair:>6}件  ← 共起ペア生成不可")
        print(f"  共起解析対象:        {with_pair:>6}件  ← グラフへ寄与")

        word_counts = Counter(chain.from_iterable(word_sets))
        qualified = sum(1 for c in word_counts.values() if c >= min_appearance)
        print(f"  語彙総数:            {len(word_counts):>6}語")
        print(f"  閾値 ({min_appearance} 回以上):      {qualified:>6}語")

        pair_counts: Counter = Counter()
        for words in word_sets:
            if len(words) >= 2:
                pair_counts.update(combinations(sorted(words), 2))

        # Jaccard 係数 = |A∩B| / |A∪B|
        # min_cooccurrence 以下の共起回数のペアはエッジとして描画しない
        jaccard: dict[tuple[str, str], float] = {
            pair: count / (word_counts[pair[0]] + word_counts[pair[1]] - count)
            for pair, count in pair_counts.items()
            if count > min_cooccurrence
            and word_counts[pair[0]] >= min_appearance
            and word_counts[pair[1]] >= min_appearance
        }

        top_edges = sorted(jaccard.items(), key=lambda x: x[1], reverse=True)[:top_n_edges]
        G = nx.Graph()
        for (w1, w2), weight in top_edges:
            G.add_edge(w1, w2, weight=weight)

        # 孤立コンポーネント間を Jaccard 係数上位のブリッジエッジで結合
        n_comp_before = nx.number_connected_components(G)
        if n_comp_before > 1:
            g_nodes = set(G.nodes())
            bridge_pool = sorted(
                ((pair, w) for pair, w in jaccard.items()
                 if pair[0] in g_nodes and pair[1] in g_nodes
                 and not G.has_edge(*pair)),
                key=lambda x: x[1], reverse=True,
            )
            n_added = 0
            max_bridges = max(5, top_n_edges // 5)
            for (w1, w2), weight in bridge_pool:
                if n_added >= max_bridges or nx.number_connected_components(G) == 1:
                    break
                if not nx.has_path(G, w1, w2):
                    G.add_edge(w1, w2, weight=weight)
                    n_added += 1
            print(f"  ブリッジエッジ:      {n_added:>6}本 ({n_comp_before} → {nx.number_connected_components(G)} コンポーネント)")

        # 接続数 1 以下のノードを除去（末端ノード・孤立ノード）
        low_degree = [n for n in G.nodes() if G.degree(n) <= 0]
        G.remove_nodes_from(low_degree)
        if low_degree:
            print(f"  次数1以下を除去:     {len(low_degree):>6}ノード")

        print(f"  グラフ:              {G.number_of_nodes():>6}ノード / {G.number_of_edges()}エッジ")
        return G, word_counts

    def visualize(
        self,
        G: nx.Graph,
        word_counts: Counter,
        output_path: str | Path = "twitter_cooccurrence_network.png",
        fig_size: tuple[float, float] = (18.2, 11.0),  # 名刺比率 91:55
        dpi: int = 300,
        layout_k: float = 0.5,
        layout_seed: int = 42,
    ) -> None:
        """グラデーション・グロー付きダークモードネットワーク図を保存する"""

        if G.number_of_nodes() == 0:
            print("グラフにノードがありません。min_appearance / min_cooccurrence を下げて再実行してください。")
            return

        # ---- コミュニティ検出（凡例なし・色分けのみ） ----
        # scipy あり → greedy_modularity_communities、なし → label_propagation（常に実行）
        if G.number_of_edges() > 0:
            if _HAS_GREEDY:
                try:
                    try:
                        communities = list(greedy_modularity_communities(G, resolution=0.7))
                    except TypeError:
                        communities = list(greedy_modularity_communities(G))
                    large = [c for c in communities if len(c) >= 3]
                    small_nodes: set = set().union(*(c for c in communities if len(c) < 3))
                    if small_nodes and large:
                        biggest = max(large, key=len)
                        communities = [c | small_nodes if c is biggest else c for c in large]
                except Exception:
                    communities = _fallback_communities(G)
            else:
                communities = _fallback_communities(G)
        else:
            communities = [set(G.nodes())]
        node_to_comm = {n: i for i, comm in enumerate(communities) for n in comm}

        # ---- ノード属性（接続数 60% + 出現頻度 40% の複合スコア） ----
        node_list = list(G.nodes())
        degrees = dict(G.degree())
        max_degree = max(degrees.values()) if degrees else 1
        max_count = max((word_counts[n] for n in node_list), default=1)

        scores = {
            n: 0.6 * (degrees[n] / max_degree) + 0.4 * (word_counts[n] / max_count)
            for n in node_list
        }
        # 累乗スケーリング（指数 2.0）でハブと周辺ノードのサイズ差を拡大
        node_sizes = [150 + scores[n] ** 2.0 * 4000 for n in node_list]
        node_colors = [_PALETTE[node_to_comm[n] % len(_PALETTE)] for n in node_list]

        edges = list(G.edges())
        raw_weights = [G[u][v]["weight"] for u, v in edges]
        if raw_weights:
            w_min, w_max = min(raw_weights), max(raw_weights)
            w_range = w_max - w_min if w_max != w_min else 1.0
            norm = [(w - w_min) / w_range for w in raw_weights]
        else:
            norm = []

        # 密集度グラデーション反発力レイアウト
        pos = _density_gradient_layout(G, base_k=layout_k, iterations=200, seed=layout_seed)

        # 図のアスペクト比（横:縦）に合わせて x 座標をスケール
        # → 正方形のレイアウト座標が名刺比率のキャンバスを自然に埋める
        _aspect = fig_size[0] / fig_size[1]
        pos = {nd: (x * _aspect, y) for nd, (x, y) in pos.items()}

        # 最終配置の局所密度に応じてノードサイズをブースト（密集ほど大きく）
        _pos_arr = np.array([pos[nd] for nd in node_list])
        _d = _pos_arr[:, np.newaxis, :] - _pos_arr[np.newaxis, :, :]
        _dist_f = np.sqrt((_d ** 2).sum(axis=2))
        np.fill_diagonal(_dist_f, np.inf)
        _r = max(float(_pos_arr.max() - _pos_arr.min()) * 0.12, 1e-6)
        _ld = (_dist_f < _r).sum(axis=1).astype(float)
        _dn = _ld / max(float(_ld.max()), 1.0)
        node_sizes = [s * (1.0 + float(_dn[i])) for i, s in enumerate(node_sizes)]

        fig, ax = plt.subplots(figsize=fig_size)
        fig.patch.set_facecolor(_BG)
        ax.set_facecolor(_BG)

        # ---- エッジ描画（白背景向け：グレー系、重みで濃淡） ----
        for i, (u, v) in enumerate(edges):
            n = norm[i]
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            lw = 0.3 + n * 4.5
            alpha = 0.10 + n * 0.65

            # 強いエッジ（上位50%以上）にノード色由来のグロー
            if n > 0.50:
                glow_alpha = (n - 0.50) * 0.18
                ax.plot([x0, x1], [y0, y1],
                        color=(0.20, 0.35, 0.75, glow_alpha),
                        linewidth=lw * 3.5,
                        solid_capstyle="round", zorder=1)

            # メインエッジ（薄グレー → 濃グレー青のグラデーション）
            ax.plot([x0, x1], [y0, y1],
                    color=(0.30 + n * 0.15, 0.35 + n * 0.10, 0.55 + n * 0.10, alpha),
                    linewidth=lw,
                    solid_capstyle="round", zorder=2)

        # ---- ノード描画 ----
        # ハブノード（複合スコア上位30%）に多層グロー
        hub_mask = [scores[n] >= 0.30 for n in node_list]
        hub_nodes = [n for n, h in zip(node_list, hub_mask) if h]
        hub_sizes = [s for s, h in zip(node_sizes, hub_mask) if h]
        hub_colors = [c for c, h in zip(node_colors, hub_mask) if h]

        if hub_nodes:
            # 外層グロー（広く・極薄）
            pc = nx.draw_networkx_nodes(
                G, pos, ax=ax, nodelist=hub_nodes,
                node_size=[s * 5.0 for s in hub_sizes],
                node_color=hub_colors,
                alpha=0.08, linewidths=0,
            )
            if pc is not None:
                pc.set_zorder(3)
            # 内層グロー（中程度・薄）
            pc = nx.draw_networkx_nodes(
                G, pos, ax=ax, nodelist=hub_nodes,
                node_size=[s * 2.5 for s in hub_sizes],
                node_color=hub_colors,
                alpha=0.18, linewidths=0,
            )
            if pc is not None:
                pc.set_zorder(4)

        # メインノード（白枠で隣接ノードとの境界を明確化）
        pc = nx.draw_networkx_nodes(
            G, pos, ax=ax,
            node_size=node_sizes,
            node_color=node_colors,
            alpha=0.92, linewidths=0.8, edgecolors="#ffffff",
        )
        if pc is not None:
            pc.set_zorder(5)

        # ---- ラベル描画 ----
        # 複合スコアに比例したフォントサイズ、白ボックスで漢字を明確に描画
        for node in node_list:
            x, y = pos[node]
            sc = scores[node]
            # スコアに応じて 6〜18pt。ハブは大きく・太く
            fsize = max(6, min(18, 6 + int(sc ** 0.55 * 12)))
            is_hub = sc >= 0.30

            ax.text(
                x, y, node,
                fontsize=fsize,
                fontfamily=_JP_FONT,
                ha="center", va="center",
                color="#111111" if is_hub else "#444444",
                fontweight="bold" if is_hub else "normal",
                bbox=dict(
                    boxstyle="round,pad=0.15",
                    facecolor="white",
                    alpha=0.80,
                    edgecolor="none",
                ),
                zorder=8,
            )

        ax.set_title(
            "Twitter Co-occurrence Network",
            fontsize=20, fontweight="bold", pad=20,
            color="#222222",
        )
        ax.axis("off")

        stats = (
            f"ノード: {G.number_of_nodes()}   "
            f"エッジ: {G.number_of_edges()}   "
            f"コミュニティ: {len(communities)}"
        )
        fig.text(0.5, 0.01, stats, ha="center", fontsize=10, color="#888888")

        output_path = Path(output_path)
        fig.savefig(output_path, bbox_inches="tight", dpi=dpi, facecolor=fig.get_facecolor())
        plt.close(fig)
        print(f"ネットワーク図を {output_path} として保存しました。")


def _diagnose(analyzer: "TweetCooccurrenceNetwork", tweets: list[str], n: int = 5) -> None:
    """データが0件になる原因を診断する"""
    print("\n--- 診断モード ---")
    print(f"サンプル（先頭 {n} 件）:")
    for i, t in enumerate(tweets[:n]):
        cleaned = analyzer._clean(t)
        nouns = analyzer._extract_nouns(t)
        print(f"  [{i+1}] 元テキスト: {t[:80]!r}")
        print(f"       クリーン後: {cleaned[:80]!r}")
        print(f"       抽出名詞:   {nouns}")
    print("-------------------\n")


if __name__ == "__main__":
    FILE_PATH = "tweets.js"

    # lang: "auto"（日本語↔英語を自動判定） / "ja" / "en" / "both"（バイリンガル）
    LANG = "both"

    try:
        analyzer = TweetCooccurrenceNetwork(FILE_PATH, lang=LANG)
        print("\nツイートデータを読み込んでいます...")
        tweets = analyzer.load_tweets()
        print(f"読み込みツイート数: {len(tweets)}件\n")

        print("共起ネットワークを解析中...")
        G, word_counts = analyzer.build_graph(
            tweets,
            min_appearance=3,
            top_n_edges=350,
            min_cooccurrence=3,
        )

        # 共起解析対象が0件の場合に診断情報を表示
        if G.number_of_nodes() == 0:
            _diagnose(analyzer, tweets)

        print("\nネットワーク図を描画中...")
        analyzer.visualize(G, word_counts)

    except FileNotFoundError:
        print(f"エラー: '{FILE_PATH}' が見つかりません。パスを確認してください。")
    except ValueError as e:
        print(f"データ解析エラー: {e}")
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}")
