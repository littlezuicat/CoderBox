# -*- coding: utf-8 -*-
"""logprog 的离线测试：用各种常见训练日志格式（去雾/复原方向常见的 BasicSR、MMagic、FFA-Net、KAIR、tqdm、Lightning…）验证进度识别。
运行：.venv\\Scripts\\python.exe tools\\test_logprog.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py"))
from majing.core import logprog as L  # noqa: E402

NOW = 1_800_000_000.0
FAILS = []


def check(name, r, frac=None, kind=None, eta_src=None, stage=None, tol=0.01, label_has=None, frac_none=False):
    ok = True
    why = []
    if frac_none:
        if r["frac"] is not None:
            ok = False
            why.append("frac 应为 None，实际 %s" % r["frac"])
    elif frac is not None:
        if r["frac"] is None or abs(r["frac"] - frac) > tol:
            ok = False
            why.append("frac 应为 %.4f，实际 %s" % (frac, r["frac"]))
    if kind and r["kind"] != kind:
        ok = False
        why.append("kind 应为 %s，实际 %s" % (kind, r["kind"]))
    if eta_src and r["eta_src"] != eta_src:
        ok = False
        why.append("eta_src 应为 %s，实际 %s" % (eta_src, r["eta_src"]))
    if stage and stage not in r["stage"]:
        ok = False
        why.append("stage 应含 %s，实际 %s" % (stage, r["stage"]))
    if label_has and label_has not in r["label"]:
        ok = False
        why.append("label 应含 %s，实际 %s" % (label_has, r["label"]))
    print(("通过" if ok else "失败"), "|", name, "|", "frac=%s" % (None if r["frac"] is None else round(r["frac"], 4)), r["label"], "| eta", r["eta_s"], r["eta_src"], "|", r["stage"], "".join(" ✗" + w for w in why))
    if not ok:
        FAILS.append(name)


# 1. BasicSR（Restormer / NAFNet / DehazeFormer-BasicSR 版 …）：日志开头打印配置，行里自带 eta
head = "2024-01-02 09:00:00,001 INFO: \n  name: Dehaze_NAFNet\n  train:\n    total_iter: 300000\n    warmup_iter: -1\n"
tail = "\n".join("2024-01-02 10:%02d:00,123 INFO: [Dehaz..][epoch:  5, iter:  %s, lr:(2.000e-04,)] [eta: 1 day, 2:13:45, time (data): 0.412 (0.003)] l_pix: 1.2345e-02" % (i, format(10000 + i * 100, ",")) for i in range(10))
r = L.analyze(head, tail, cmd="python basicsr/train.py -opt options/train/NAFNet-dehaze.yml --launcher none", now=NOW, mtime=NOW - 5)
check("BasicSR", r, frac=10900 / 300000, kind="iter", eta_src="log")
print("   名字：", L.guess_name("python basicsr/train.py -opt options/train/NAFNet-dehaze.yml --launcher none", "/data/proj"))

# 2. MMagic / mmengine
tail = "\n".join("11/20 10:%02d:33 - mmengine - INFO - Iter(train) [%6d/300000]  lr: 1.0000e-04  eta: 1 day, 2:03:04  time: 0.5  data_time: 0.01  memory: 12000  loss: 0.12" % (i, 1000 + i * 50) for i in range(10))
check("MMagic", L.analyze("", tail, cmd="python tools/train.py configs/x.py", now=NOW), frac=1450 / 300000, kind="iter", eta_src="log")

# 3. 老 mmcv：Epoch [3][100/500]，总轮数在配置里
tail = "\n".join("2021-05-01 10:00:%02d,000 - mmedit - INFO - Epoch [3][%d/500]\tlr: 1.000e-04, eta: 2:03:11, time: 0.5, data_time: 0.1, loss: 0.1" % (i, 100 + i * 10) for i in range(5))
check("mmcv Epoch[3][100/500]", L.analyze("", tail, cfg_text="runner = dict(type='EpochBasedRunner', max_epochs=12)", now=NOW), frac=(3 - 1 + 140 / 500) / 12, kind="epoch", eta_src="log")

# 4. tqdm：Epoch 3/100 + 回车刷新的进度条
bar = "".join("\rEpoch 3/100:  %d%%|████▌     | %d/1000 [02:11<02:40,  3.4it/s, loss=0.12]" % (p // 10, p) for p in range(400, 460, 10))
check("tqdm Epoch 3/100", L.analyze("Epoch 1/100: 100%|██| 1000/1000\n", "Epoch 2/100: 100%|██| 1000/1000 [05:00<00:00]\n" + bar, now=NOW), frac=(3 - 1 + 0.45) / 100, kind="epoch")

# 5. Lightning：Epoch 3 是 0 起，总数在命令里
head = "Epoch 0:  100%|██| 1000/1000 [05:00<00:00, 3.3it/s, v_num=1]\nEpoch 1: 100%|██| 1000/1000 [05:00<00:00]\n"
bar = "".join("\rEpoch 3:  %d%%|████▌     | %d/1000 [02:11<02:40,  3.4it/s, v_num=1, loss=0.12]" % (p // 10, p) for p in range(400, 460, 10))
check("Lightning", L.analyze(head, bar, cmd="python train.py --max_epochs 100", now=NOW), frac=(3 + 0.45) / 100, kind="epoch")

# 6. FFA-Net 风格
tail = "".join("\rtrain loss:0.00123 |step :%d/20000|lr :0.00010000|time_used :0.5h" % (1200 + i) for i in range(30))
check("FFA-Net step", L.analyze("", tail, cmd="python main.py --net='ffa' --crop --crop_size=240 --blocks=19 --gps=3 --bs=2 --lr=0.0001 --trainset='its_train' --steps=20000 --eval_step=5000", now=NOW), frac=1229 / 20000, kind="iter")

# 7. 每个 epoch 一行，没有总数，总数在命令里
tail = "\n".join("Epoch %d, loss: 0.12 psnr 30.1" % e for e in range(100, 124))
head = "Epoch 1, loss: 0.9\nEpoch 2, loss: 0.8\n"
check("一行一个 epoch（--epochs 1000）", L.analyze(head, tail, cmd="python train.py --epochs 1000", now=NOW), frac=123 / 1000, kind="epoch")

# 8. Epoch [123/1000]
tail = "\n".join("Epoch [%d/1000] Loss: 0.12 PSNR: 28.1" % e for e in range(100, 124))
check("Epoch [123/1000]", L.analyze("", tail, now=NOW), frac=123 / 1000, kind="epoch")

# 9. KAIR：没有总数 → 不瞎编
tail = "\n".join("23-11-20 10:%02d:33.123 : <epoch:  3, iter:   %5d, lr:2.000e-04> G_loss: 1.234e-02" % (i, 200 + 200 * i) for i in range(10))
check("KAIR（总数缺失）", L.analyze("", tail, now=NOW), frac_none=True, label_has="总数没识别到")

# 9b. KAIR + 命令里能找到总数 → 用得上
check("KAIR（有 --total_iter）", L.analyze("", tail, cmd="python main_train_psnr.py --opt options/swinir.json --total_iter 500000", now=NOW), frac=2000 / 500000, kind="iter")

# 10. HuggingFace Trainer：epoch 是小数
tail = "\n".join("{'loss': 0.3, 'learning_rate': 4.5e-05, 'epoch': %.2f}" % (0.05 * i) for i in range(1, 10))
check("HF Trainer", L.analyze("", tail, cmd="python run.py --num_train_epochs 3", now=NOW), frac=0.45 / 3, kind="epoch")

# 11. MNIST 样式
tail = "\n".join("Train Epoch: 3 [%d/6000 (%d%%)]\tLoss: 0.1" % (200 * i, 200 * i / 60) for i in range(1, 7))
check("Train Epoch: 3 [1200/6000 (20%)]", L.analyze("", tail, cmd="python main.py --epochs 14", now=NOW), frac=(3 - 1 + 0.2) / 14, kind="epoch")

# 12. 只有进度条（扩散模型常见：按 step 的 tqdm）
bar = "".join("\rloss: 0.0123:  %d%%|████▌     | %d/10000 [05:00<06:00, 15.0it/s]" % (p // 100, p) for p in range(4400, 4500, 20))
check("只有 tqdm 条", L.analyze("", bar, now=NOW), frac=0.448, kind="bar", eta_src="log")

# 13. 阶段：验证中
tail = "\n".join(["Epoch [5/100] Iter [100/500] loss 0.1", "Epoch [5/100] Iter [200/500] loss 0.1", "Start validation...", "Validation PSNR: 31.2 SSIM: 0.95"])
check("阶段=验证", L.analyze("", tail, now=NOW), stage="验证")

# 14. 阶段：保存
tail = "\n".join(["Epoch [5/100] Iter [200/500] loss 0.1", "Saving model to experiments/x/models/net_5.pth"])
check("阶段=保存", L.analyze("", tail, now=NOW), stage="保存")

# 15. 出错
tail = "\n".join(["Epoch [5/100] Iter [200/500] loss 0.1", "Traceback (most recent call last):", "  File x", "RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB"])
r = L.analyze("", tail, now=NOW)
print("   错误：", r["error"])
if "out of memory" not in r["error"]:
    FAILS.append("错误识别")

# 16. CycleGAN：总轮数 = n_epochs + n_epochs_decay
tail = "\n".join("(epoch: 5, iters: %d, time: 0.1, data: 0.0) G_GAN: 0.5" % (100 * i) for i in range(1, 6))
check("CycleGAN", L.analyze("", tail, cmd="python train.py --n_epochs 100 --n_epochs_decay 100", now=NOW), frac=(5 - 1 + 1) / 200, kind="epoch")

# 17. 一行一个 epoch + 时间戳 → 用时间戳算速度
tail = "\n".join("2024-01-02 %02d:%02d:00 Epoch %d/100 loss 0.1" % (10 + (e * 2) // 60, (e * 2) % 60, e) for e in range(1, 21))
r = L.analyze("", tail, now=NOW)
check("时间戳速度", r, frac=0.2, kind="epoch", eta_src="rate")
print("   预计剩余秒：", r["eta_s"], "（应约 80 轮 × 120 秒 = 9600）")
if not r["eta_s"] or abs(r["eta_s"] - 9600) > 600:
    FAILS.append("时间戳速度的 eta")

# 18. 没有任何进度的日志
check("没有进度", L.analyze("", "Loading dataset...\nBuilding model\nTotal params: 12M", now=NOW), frac_none=True, stage="加载")

# 19. 空日志
check("空日志", L.analyze("", "", now=NOW), frac_none=True, stage="启动中")

# 20. 靠启动时间粗估
tail = "\n".join("Epoch %d, loss: 0.12" % e for e in range(1, 21))
r = L.analyze("", tail, cmd="python train.py --epochs 100", now=NOW, started=NOW - 2000)
check("粗估（启动时间）", r, frac=0.2, kind="epoch", eta_src="elapsed")

# 21. 训练条之后跟着一条验证进度条：不能被当成训练进度
bar = "".join("\rEpoch 3/100:  %d%%|████▌     | %d/1000 [02:11<02:40,  3.4it/s, loss=0.12]" % (p // 10, p) for p in range(400, 460, 10))
val = "\nValidation:  60%|██████    | 30/50 [00:10<00:07, 2.9it/s]"
check("验证条不算", L.analyze("", bar + val, now=NOW), frac=(3 - 1 + 0.45) / 100, kind="epoch")

# 22. ImageNet 样例风格：Epoch: [12][ 100/5005]
tail = "\n".join("Epoch: [12][%4d/5005]\tTime 0.5 (0.5)\tLoss 0.1" % (100 + i * 100) for i in range(5))
check("Epoch: [12][100/5005]", L.analyze("", tail, cmd="python main.py --epochs 90", now=NOW), frac=(12 - 1 + 500 / 5005) / 90, kind="epoch")

# 23. PyTorch-GAN 风格：[Epoch 12/200] [Batch 100/500]
tail = "\n".join("[Epoch 12/200] [Batch %d/500] [D loss: 0.5] [G loss: 1.2]" % (100 + i * 10) for i in range(5))
check("[Epoch 12/200] [Batch 100/500]", L.analyze("", tail, now=NOW), frac=(12 - 1 + 140 / 500) / 200, kind="epoch")

# 24. 整个训练一个进度条（DehazeFormer：for epoch in tqdm(range(epochs+1))）
bar = "".join("\r %d%%|██▌   | %d/301 [10:23<4:11:20, 52.1s/it]" % (n * 100 // 301, n) for n in range(10, 13))
r = L.analyze("", bar, cmd="python train.py --model dehazeformer-b --dataset RESIDE-IN --exp indoor", cfg_text="epochs: 300", now=NOW)
check("整训练 tqdm", r, frac=12 / 301, kind="bar", eta_src="log", label_has="epoch 12 / 301")

# 25. RT-DETR / DETR 风格：eta 只是当前这一轮剩余的；总轮数在配置文件里（epoches）
LEN = 640
tail = "\n".join("Epoch: [309]  [%4d/1617]  eta: %d:%02d:%02d  lr: 0.000010  loss: 17.5840 (17.8345)  loss_vfl: 0.4198 (0.4350)" % (b, int(LEN * (1 - b / 1617)) // 3600, int(LEN * (1 - b / 1617)) % 3600 // 60, int(LEN * (1 - b / 1617)) % 60) for b in range(0, 1617, 100))
r = L.analyze("", tail, cmd="python tools/train.py -c configs/rtdetr/x.yml", cfg_text="epoches: 500\n", now=NOW)
check("DETR 每轮 eta", r, frac=(309 - 0 + 1500 / 1617) / 500, kind="epoch", eta_src="epoch-eta", tol=0.004)
exp_eta = 640 * (1 - 1600 / 1617) + (500 - 309 - 1) * 640
print("   总剩余秒：", r["eta_s"], "（应约", int(exp_eta), "）")
if not r["eta_s"] or abs(r["eta_s"] - exp_eta) > 0.1 * exp_eta:
    FAILS.append("DETR 每轮 eta 推算")

# 26. 同样格式但 eta 是整个训练的（mmcv）→ 不能再乘一遍
tail = "\n".join("Epoch [3][%d/500]\tlr: 1.000e-04, eta: %d:%02d:%02d, time: 0.5" % (b, (50000 - b * 2) // 3600, (50000 - b * 2) % 3600 // 60, (50000 - b * 2) % 60) for b in range(0, 500, 50))
r = L.analyze("", tail, cfg_text="max_epochs=12", now=NOW)
check("mmcv 总 eta 不重复算", r, eta_src="log")
print("   eta：", r["eta_s"], "（应约 49100）")
if not r["eta_s"] or abs(r["eta_s"] - 49100) > 600:
    FAILS.append("mmcv eta")

# 27. 真实自定义格式（服务器上跑的 dehaze.py）：Epoch 2  update 3250/3385 …，每轮结束一行 Epoch 1/10 … validation PSNR
head = "Prepared 35 training images, 330 positions and 3385 updates per epoch at batch size 2.\nEpoch 1  update 1/3385  position (1, 1)  scenes 14,29  loss 0.92228\n"
tail = "Epoch 1/10  loss 0.74332  validation PSNR 18.43 dB\n" + "\n".join("Epoch 2  update %d/3385  position (14, 8)  scenes 19,5  loss 0.712" % u for u in range(3000, 3300, 50))
r = L.analyze(head, tail, cmd="python3 -u dehaze.py train --epochs 10 --schedule-epochs 55 --log-every 50", now=NOW)
check("dehaze.py 自定义格式", r, frac=(2 - 1 + 3250 / 3385) / 10, kind="epoch", tol=0.012)
print("   指标：", r["metrics"])

print()
if FAILS:
    print("失败项：", FAILS)
    sys.exit(1)
print("全部通过")
