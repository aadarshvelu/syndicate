# Embedding model benchmark — news dedup

_Generated: 2026-05-01 17:02:49 UTC_

## Models

| Name | Repo | Params | Disk | License | Load (ms) | Avg embed (ms) |
|------|------|--------|------|---------|-----------|----------------|
| qwen | qwen3-embedding:latest | 600M | 1200 MB | Apache-2.0 | 341 | 302.9 |
| gemma | embeddinggemma:latest | 308M | 600 MB | Gemma | 139 | 112.5 |

## Per-pair cosine similarity

| Pair | Kind | Expected | qwen | gemma |
|------|------|----------|----|----|
| p01_identical | identical | very_high | 1.000 | 1.000 |
| p02_paraphrase_close | paraphrase | high | 0.932 | 0.879 |
| p03_same_story_diff_framing | same_topic | high | 0.935 | 0.941 |
| p04_outlet_rewrite | same_topic | high | 0.905 | 0.887 |
| p05_event_summary_vs_quote | same_topic | high | 0.817 | 0.579 |
| p06_paywall_lede_only | same_topic | moderate | 0.762 | 0.616 |
| p07_same_topic_different_news | different_story | low | 0.507 | 0.387 |
| p08_same_company_different_topic | different_story | low | 0.444 | 0.381 |
| p09_finance_event_pair | paraphrase | high | 0.825 | 0.834 |
| p10_paywall_teaser_vs_full_body | same_topic | high | 0.629 | 0.522 |
| p11_unrelated_tech_v_finance | unrelated | very_low | 0.419 | 0.242 |
| p12_unrelated_random | unrelated | very_low | 0.466 | 0.306 |
| p13_same_story_with_outlet_chrome | same_topic | high | 0.662 | 0.386 |
| p14_partial_overlap_long_v_short | same_topic | high | 0.695 | 0.568 |

## Mean cosine by pair kind

| Kind | qwen | gemma |
|------|----|----|
| different_story | 0.476 | 0.384 |
| identical | 1.000 | 1.000 |
| paraphrase | 0.878 | 0.856 |
| same_topic | 0.772 | 0.643 |
| unrelated | 0.443 | 0.274 |

## Pair texts (for reference)

**p01_identical** (identical, expected=very_high)
- A: OpenAI announces GPT-5 with new agent capabilities and improved reasoning.
- B: OpenAI announces GPT-5 with new agent capabilities and improved reasoning.

**p02_paraphrase_close** (paraphrase, expected=high)
- A: OpenAI ships GPT-5 with improved reasoning and new agent features.
- B: OpenAI launches GPT-5 featuring better reasoning and new agentic capabilities.

**p03_same_story_diff_framing** (same_topic, expected=high)
- A: OpenAI buys Windsurf, the AI coding startup, in a $3 billion all-stock deal.
- B: AI coding company Windsurf has been acquired by OpenAI for around three billion dollars in stock.

**p04_outlet_rewrite** (same_topic, expected=high)
- A: Anthropic raises $4 billion at a $61 billion valuation, led by Lightspeed Venture Partners.
- B: Lightspeed leads Anthropic's $4B funding round at a $61 billion post-money valuation.

**p05_event_summary_vs_quote** (same_topic, expected=high)
- A: Apple unveils on-device foundation models powering Apple Intelligence, with privacy guarantees.
- B: Apple's Craig Federighi: 'Apple Intelligence runs locally on-device, your data never leaves your iPhone.'

**p06_paywall_lede_only** (same_topic, expected=moderate)
- A: Why Nvidia's $4 trillion market cap might still be cheap.
- B: Nvidia hits $4T valuation amid record demand for AI chips; analysts split on whether shares are overvalued.

**p07_same_topic_different_news** (different_story, expected=low)
- A: OpenAI partners with AWS in a multi-year compute deal worth tens of billions.
- B: OpenAI launches Sora 2, its next-generation text-to-video model, to ChatGPT Pro users.

**p08_same_company_different_topic** (different_story, expected=low)
- A: Meta's Reality Labs posts another quarterly loss as VR headset sales slow.
- B: Meta open-sources Llama 4, claiming GPT-4-class performance on standard benchmarks.

**p09_finance_event_pair** (paraphrase, expected=high)
- A: The Federal Reserve held interest rates steady at its July meeting, citing persistent inflation.
- B: Fed leaves rates unchanged in July; officials point to sticky inflation as the reason for the pause.

**p10_paywall_teaser_vs_full_body** (same_topic, expected=high)
- A: American Efficient, Pershing Square USA, BJ's.
- B: Matt Levine writes about American Efficient's electricity arbitrage business, the Pershing Square USA IPO and BJ's Wholesale Club's quarter.

**p11_unrelated_tech_v_finance** (unrelated, expected=very_low)
- A: GitHub releases new code review features powered by AI for enterprise customers.
- B: Spirit Airlines and the future of cheap flights: how budget carriers are restructuring after fuel-price shocks.

**p12_unrelated_random** (unrelated, expected=very_low)
- A: How goblins came from: GPT-5.1's strange habit of mentioning fantasy creatures in its metaphors.
- B: Battlefield rare earths: How the U.S. lost to China in the rare-earths supply chain over four decades.

**p13_same_story_with_outlet_chrome** (same_topic, expected=high)
- A: Comments URL: https://news.ycombinator.com/item?id=12345 Points: 412 Article: OpenAI ships new model.
- B: Today, we're introducing our next-generation model. It improves on reasoning, code, and following user instructions.

**p14_partial_overlap_long_v_short** (same_topic, expected=high)
- A: Sell the Electricity No One Is Using.
- B: American Efficient buys electricity from grid operators that no one is using and resells it back to the same operators, profiting from the fact that the grid pays for capacity that doesn't get consumed. The story is essentially a market arbitrage on demand-response capacity payments and the company is profitable enough that the question is whether this is fraud or genius.
