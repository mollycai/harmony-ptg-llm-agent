import pandas as pd
import matplotlib.pyplot as plt

# 配色方案 2：暖色对比风（酒红-橙-灰蓝）
PRIMARY_SC = '#8C1C13'
PRIMARY_PC = '#E07A1F'
COMPARE_SC = '#6C8EAD'
COMPARE_PC = '#A3B8CC'
PRIMARY_LINE = '#8C1C13'
COMPARE_LINE = '#4F6D7A'
AN_PRIMARY = '#B85042'
AN_COMPARE = '#4F6D7A'
TIME_CMAP = 'plasma'

# ===== 1. 读取Excel =====
file_path = "data/results.xlsx"   # 修改为你的路径
sheet_name = "LMT vs SAMT"

df = pd.read_excel(file_path, sheet_name=sheet_name)

# ===== 2. 数据提取 =====
time = df['Times(s)']

llm_sc = df['LLM PTG-based Testing SC']
llm_pc = df['LLM PTG-based Testing PC']
llm_an = df['LLM PTG-based Testing AN']

rand_sc = df['SA PTG-based Testing SC']
rand_pc = df['SA PTG-based Testing PC']
rand_an = df['SA PTG-based Testing AN']

# 创建子图
fig, axs = plt.subplots(1, 3, figsize=(15,4))

# ===================== (a) Time → Coverage =====================
axs[0].plot(time, llm_sc, marker='o', color=PRIMARY_SC, label='LLMPTG-SC')
axs[0].plot(time, llm_pc, marker='s', color=PRIMARY_PC, label='LLMPTG-PC')

axs[0].plot(time, rand_sc, marker='o', linestyle='--', color=COMPARE_SC, label='SAPTG-SC', alpha=0.9)
axs[0].plot(time, rand_pc, marker='s', linestyle='--', color=COMPARE_PC, label='SAPTG-PC', alpha=0.9)

axs[0].set_xlabel('Time (sec)')
axs[0].set_ylabel('Coverage (%)')
axs[0].set_title('(a) Coverage vs Time')
axs[0].grid(alpha=0.3)
axs[0].legend(fontsize=8)

# ===================== (b) Time → AN =====================
axs[1].plot(time, llm_an, marker='o', color=AN_PRIMARY, label='LLMPTG')
axs[1].plot(time, rand_an, marker='x', linestyle='--', color=AN_COMPARE, label='SAPTG')

axs[1].set_xlabel('Time (sec)')
axs[1].set_ylabel('Action Number (AN)')
axs[1].set_title('(b) Actions vs Time')
axs[1].grid(alpha=0.3)
axs[1].legend(fontsize=8)

# ===================== (c) AN → Coverage =====================
sc = axs[2].scatter(llm_an, llm_pc, c=time, cmap=TIME_CMAP, s=60, label='LLMPTG')
axs[2].plot(llm_an, llm_pc, color=PRIMARY_LINE)

axs[2].scatter(rand_an, rand_pc, c=time, cmap=TIME_CMAP, marker='x', s=60, label='SAPTG')
axs[2].plot(rand_an, rand_pc, linestyle='--', color=COMPARE_LINE)

axs[2].set_xlabel('Action Number (AN)')
axs[2].set_ylabel('Path Coverage (PC %)')
axs[2].set_title('(c) Efficiency (AN vs PC)')
axs[2].grid(alpha=0.3)
axs[2].legend(fontsize=8)

# colorbar（时间）
cbar = fig.colorbar(sc, ax=axs[2])
cbar.set_label('Time (sec)')

# 布局
plt.tight_layout()

plt.savefig("data/diagram_2.png", bbox_inches="tight")

plt.show()
