# 导入 RT-DETR / RT-DETRv2 训练日志

两个上游 PyTorch solver 都会在训练输出目录里追加 JSONL `log.txt`。这个文件每行是一条 epoch 记录，包含 `epoch` 和 `test_coco_eval_bbox`。终端重定向生成的训练 stdout 是另一种格式。导入器从 COCO 指标数组下标 0 读取主 AP，从下标 3 读取 AP_small。`-1` 是 COCO 的不可用值，会显示为缺失。

来源：[RT-DETR solver](https://github.com/lyuwenyu/RT-DETR/blob/main/rtdetr_pytorch/src/solver/det_solver.py) · [RT-DETRv2 solver](https://github.com/lyuwenyu/RT-DETR/blob/main/rtdetrv2_pytorch/src/solver/det_solver.py) · [COCO 指标顺序](https://github.com/cocodataset/cocoapi/blob/master/PythonAPI/pycocotools/cocoeval.py)

在已完成的实验旁新建导入清单。每条运行指定实际使用的日志、数据划分、固定训练条件和评估条件。相对路径以清单所在目录为准。

```json
{
  "version": 1,
  "runs": [
    {
      "run_id": "DET-101",
      "label": "RT-DETRv2 baseline",
      "revision": "替换成训练时的代码版本",
      "seed": 42,
      "epoch": 71,
      "log": "baseline/log.txt",
      "train_manifest": "splits/train.json",
      "validation_manifest": "splits/val.json",
      "training_controls": "controls/train.json",
      "evaluation_controls": "controls/eval.json"
    },
    {
      "run_id": "DET-102",
      "label": "RT-DETRv2 + 候选模块",
      "revision": "替换成候选训练时的代码版本",
      "seed": 42,
      "epoch": 71,
      "log": "candidate/log.txt",
      "train_manifest": "splits/train.json",
      "validation_manifest": "splits/val.json",
      "training_controls": "controls/train.json",
      "evaluation_controls": "controls/eval.json"
    }
  ]
}
```

- `epoch` 是日志中的零起始值。72 个 epoch 的训练通常填写 `71`，它和日志行号是两回事。清单缺少该 epoch、重复记录该 epoch 或指标损坏时，导入命令会报出文件位置。
- `train_manifest` 和 `validation_manifest` 可以是各自的 COCO 标注或带样本内容校验值的清单。导入器按原始文件字节计算指纹。两个运行必须引用各自真正使用过的文件。
- `training_controls` 记录应该固定的训练条件，如训练预算、优化器、学习率调度、数据增强、batch size、精度和预训练权重来源。消融模块单独由代码版本标识。若训练条件不同，应分别登记对应文件。
- `evaluation_controls` 记录评估器版本、推理尺寸、精度、EMA 选择及后处理设置。控制文件是实验者登记的 JSON 对象，导入器通过规范化键顺序计算指纹。文件应完整反映实际实验设置。
- 每条导入记录保存日志文件名、匹配行号、epoch 和整份日志的 SHA-256。Agent 会把这些信息显示在运行证据中。不同 epoch 或不完整的取分证据会影响可比性判断。

在 `experiment-pilot/` 运行：

```bash
uv run --locked experiment-pilot-import /path/to/import.json --output /path/to/catalog.json
PILOT_RUNS_FILE=/path/to/catalog.json uv run --locked uvicorn experiment_pilot.api:app
```

启动后可在工作台的实验目录点击编号，把它加入问题。输入两条编号即可对比，顺序为基线、候选。

使用新的输出文件名。导入成功后只会发布完整的目录快照。如果目标文件已经存在，命令会提示换文件名。导入及复盘只读取实验产物。
