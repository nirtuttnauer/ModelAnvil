---
language:
- en
license: mit
task_categories:
- text-generation
pretty_name: UltraFeedback Binarized
configs:
- config_name: default
  data_files:
  - split: train_prefs
    path: data/train_prefs-*
  - split: train_sft
    path: data/train_sft-*
  - split: test_prefs
    path: data/test_prefs-*
  - split: test_sft
    path: data/test_sft-*
  - split: train_gen
    path: data/train_gen-*
  - split: test_gen
    path: data/test_gen-*
dataset_info:
  features:
  - name: prompt
    dtype: string
  - name: prompt_id
    dtype: string
  - name: chosen
    list:
    - name: content
      dtype: string
    - name: role
      dtype: string
  - name: rejected
    list:
    - name: content
      dtype: string
    - name: role
      dtype: string
  - name: messages
    list:
    - name: content
      dtype: string
    - name: role
      dtype: string
  - name: score_chosen
    dtype: float64
  - name: score_rejected
    dtype: float64
  splits:
  - name: train_prefs
    num_bytes: 405688662
    num_examples: 61135
  - name: train_sft
    num_bytes: 405688662
    num_examples: 61135
  - name: test_prefs
    num_bytes: 13161585
    num_examples: 2000
  - name: test_sft
    num_bytes: 6697333
    num_examples: 1000
  - name: train_gen
    num_bytes: 325040536
    num_examples: 61135
  - name: test_gen
    num_bytes: 5337695
    num_examples: 1000
  download_size: 649967196
  dataset_size: 1161614473
---

# Dataset Card for UltraFeedback Binarized

## Dataset Description

This is a pre-processed version of the [UltraFeedback dataset](https://huggingface.co/datasets/openbmb/UltraFeedback) and was used to train [Zephyr-7Β-β](https://huggingface.co/HuggingFaceH4/zephyr-7b-beta), a state of the art chat model at the 7B parameter scale. 

The original UltraFeedback dataset consists of 64k prompts, where each prompt is accompanied with four model completions from a wide variety of open and proprietary models. GPT-4 is then used to assign a score to each completion, along criteria like helpfulness and honesty. To create `UltraFeedback Binarized`, we picked the highest `overall_score` as the "chosen" completion, and one of the remaining 3 at random as the "rejected" one. This defines the preference modelling splits for techniques like reward modelling or DPO. We also created splits for supervised fine-tuning (SFT) that use the "chosen" column as the dialogues to model, along with splits that involve generation like rejection sampling or PPO. For details on the dataset processing, see the accompanying [script](https://huggingface.co/datasets/HuggingFaceH4/ultrafeedback_binarized/blob/main/create_dataset.py).

## Dataset Structure

### Usage

To load the dataset, run:

```python
from datasets import load_dataset

ds = load_dataset("HuggingFaceH4/ultrafeedback_binarized")
```

**Note:** after the release of Zephyr-7b-β, the team at [Argilla](https://huggingface.co/argilla) noted that there were a few hundred completions with the incorrect label. Similarly, members of the community pointed out that a several prompts were sourced from the TruthfulQA benchmark which can lead to contamination with public leaderboards. Both of these issues have been resolved in the latest version of the dataset, but if you wish to use the older version, you can run:

```python
from datasets import load_dataset

ds = load_dataset("HuggingFaceH4/ultrafeedback_binarized", revision="292c16329d921287c4166934cac1a6ad1e13a6c5")
```

### Data Splits

The dataset has six splits, suitable for:

* Supervised fine-tuning (`sft`).
* Preference modelling (`prefs`) to train reward models or apply techniques like DPO.
* Generation ranking (`gen`) via techniques like rejection sampling or PPO.

The number of examples per split is shown as follows:


|  train_sft | test_sft | train_prefs | test_prefs | train_gen | test_gen |
|:-------:|:-----------:|:-----:| :-----:| :-----:| :-----:|
|  61135 |       1000 | 61135 | 2000 | 61135 | 1000 |


The dataset is stored in parquet format with each entry using the following schema:

```
{
    "prompt": "Which books are still banned in Canada?",
    "chosen": [
    {
        "content": "Which books are still banned in Canada?", 
        "role": "user"
    },
    {
        "content": "As a responsible and ethical AI assistant, I must inform you that I cannot provide a list of banned books in Canada, as there are no books that are currently banned in the country. Canada has a strong commitment to freedom of expression and the right to access information, and there are no laws in place that restrict the publication or distribution of books.\n",
        "role": "assistant"
        }
    ],
 "messages": [
     {
         "content": "Which books are still banned in Canada?",
         "role": "user"
    },
    {
        "content": "As a responsible and ethical AI assistant, I must inform you that I cannot provide a list of banned books in Canada, as there are no books that are currently banned in the country. Canada has a strong commitment to freedom of expression and the right to access information, and there are no laws in place that restrict the publication or distribution of books.\n",
        "role": "assistant"
    }],
 
 "prompt_id": "aeccf551d9ba42fdf5f2044de43b8ce6e360fb523ace428317b81d804594e090",
 "rejected": [
     {
         "content": "Which books are still banned in Canada?",
         "role": "user"},
     {
         "content": "According to the Canadian Government’s Ban Affront website, there are still several books that are banned in Canada. These include The Begum’s Millionaire, The Education of Little Tree, The Harry Potter series, Lolita, 1984, and Lady Chatterley’s Lover. Some of these books are considered inaccessible due to their age, while others are still legally banned in certain parts of the country.",
         "role": "assistant"
         }
     ],
 "score_chosen": 8.0,
 "score_rejected": 5.0
}
```

You should use the `chosen` and `rejected` columns for techniques like DPO, while the `messages` column is suitable for SFT or PPO.

## Citation

If you find this dataset is useful in your work, please cite the original UltraFeedback dataset: 

```
@misc{cui2023ultrafeedback,
      title={UltraFeedback: Boosting Language Models with High-quality Feedback}, 
      author={Ganqu Cui and Lifan Yuan and Ning Ding and Guanming Yao and Wei Zhu and Yuan Ni and Guotong Xie and Zhiyuan Liu and Maosong Sun},
      year={2023},
      eprint={2310.01377},
      archivePrefix={arXiv},
      primaryClass={cs.CL}
}
```