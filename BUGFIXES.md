# 大肥鱼桌宠 · Bug 修复与优化清单

**修复日期**：2026-10-06
**原文件**：`桌宠.py.orig`（1043 行，原版已备份）
**修复后**：`桌宠.py`（1184 行）
**测试环境**：Windows 11 Pro · Python 3.14.2 · PySide6 6.11.2

---

## 一、严重 Bug（会崩溃或丢数据）

### 🔴 Bug 1：配置文件缺键 → 启动崩溃

**原代码**
```python
def load_json(path, default):
    ...
    return json.load(f)          # ← 原样返回，不补默认键
```

**后果**：如果 `config.json` 是旧版本写的、或被手动编辑过，缺少某些键，那么 `__init__` 里这三行**直接 KeyError 崩溃**：
```python
self.cur_h = int(340 * self.cfg["size"])              # KeyError: 'size'
self.mode = self.cfg["mode"] if ...                   # KeyError: 'mode'
if self.cfg.get("topmost", True):                     # ← 这行反而用了 get()
```

> 讽刺的是同一段代码里 `topmost` 用了 `.get()` 有默认值，`size`/`mode` 却是硬下标 —— 说明作者加字段时漏改了。

**修复**：`load_json` 改为「默认值打底 + 读取值覆盖」
```python
data = dict(default)
if isinstance(loaded, dict):
    data.update(loaded)
```
**实测**：缺键配置 → 全部键补齐，直接下标不再报错 ✅

---

### 🔴 Bug 2：穿透开关状态丢失（你实际遇到的）

**原代码**
```python
def set_passthrough(self, on):
    self.cfg["passthrough"] = bool(on)     # 只改内存
    self._apply_passthrough(bool(on))      # 窗口立即生效

def quit_app(self):                         # 唯一写文件的地方
    with open(CONFIG_PATH, "w", ...) as f:
        json.dump(self.cfg, f)
```

**后果**：**只有走菜单「退出」才写盘**。如果进程被任务管理器结束、或电脑断电/强制关机，**本次会话改的所有设置全部丢失**（模式、大小、位置、穿透）。

**你遇到的具体表现**：菜单里开了穿透 → 内存 = true、窗口穿透了 → 但强制重启后文件里还是 `false` → **文件和实际状态不一致**，鱼点不到，只能从托盘解除。

**修复**：
- 新增 `_save_cfg()`，用 `os.replace()` 原子写入（防止写一半断电损坏文件）
- `set_mode` / `set_size` / `set_passthrough` / `set_topmost` / `set_autostart` / `_set_city_dialog` / `quit_app` **全部立即落盘**

---

### 🔴 Bug 3：切换置顶会静默关掉穿透

**原代码**
```python
def set_topmost(self, on):
    self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
    self.show()      # ← 重建原生窗口，丢失 WS_EX_TRANSPARENT
```

**后果**：Qt 的 `setWindowFlag()` 会**销毁并重建底层原生窗口**，新窗口不带 `WS_EX_TRANSPARENT`。所以「先开穿透、再切换置顶」→ **穿透悄悄失效了**，但内存里 `passthrough` 仍是 true。

**修复**：切完置顶后重新应用穿透状态
```python
self._apply_passthrough(bool(self.cfg.get("passthrough", False)))
```

---

### 🔴 Bug 4：找不到精灵图 → 晦涩崩溃

**原代码**
```python
self.win_w = max(p.width() for k, p in self.sprites.items() if k[1] == self.cur_h) + ...
```

**后果**：`sprites/` 目录缺失或为空时，生成器为空，`max()` 抛 **`ValueError: max() arg is an empty sequence`** —— 用户完全看不懂发生了什么。

**修复**：新增 `cur_size_key()`，先校验精灵是否加载，缺失时弹**可读的错误框**并指明路径
```
找不到精灵图，程序无法启动。
请确认这个文件夹存在且不为空：
D:\...\sprites
```

---

### 🔴 Bug 5：托盘菜单勾选状态不同步

**原代码**
```python
self.tray.setContextMenu(self._build_menu())   # 只在 __init__ 建一次
...
pa.setChecked(self.cfg["passthrough"])         # 读取时快照
```

**后果**：从**鱼的右键菜单**改了设置，**托盘菜单的勾选状态不会更新** —— 两个菜单显示不一致，用户搞不清当前到底是什么状态。

**修复**：状态值本来就存在 `self.cfg` 里，改为菜单弹出时重建。同时把 `self.cfg["passthrough"]` 改成 `.get(...)` 防缺键。

---

## 二、内存/稳定问题

### 🟠 Bug 6：气泡消息会丢

**原代码**
```python
if self._say_queue:
    for text in self._say_queue:   # 遍历
        self.say(text)
    self._say_queue.clear()        # ← 再清空
```

**后果**：`list.append()` 是原子的，但**「遍历 + 清空」这个组合不是**。如果后台线程恰好在遍历过程中 append，这条消息会被 `clear()` **静默吞掉** —— 表现为「AI 回复偶尔不显示」。

**修复**：先原子摘取再处理
```python
pending = self._say_queue[:]
self._say_queue.clear()
for text in pending:
    self.say(text)
```

---

### 🟠 Bug 7：对话历史跨线程修改

**原代码**
```python
self.chat_history.append(...)                    # 后台线程
self.chat_history.append(...)
if len(self.chat_history) > self.max_history:
    self.chat_history = self.chat_history[-...:] # ← 非原子重建
```
`chat_history` 是**普通 list**，被后台线程和主线程同时访问，且裁剪是「先判断再重建」，中间可能被插入。

**修复**：改用 `collections.deque(maxlen=40)` —— 入队和自动裁剪都是原子的，无需手动判断。

---

## 三、体验问题

### 🟡 Bug 8：查天气冻结整个桌宠（最长 10 秒）

**原代码**：`_get_weather()` 在 **Qt 主线程**里同步发网络请求，`timeout=10`。

**后果**：点「查看天气」后，**桌宠完全卡死** —— 不走动、不呼吸、点不动、拖不动，直到请求返回或超时。

**修复**：移到后台线程，结果经 `_say_queue` 回主线程；加了 `_weather_busy` 防重复点击；天气描述映射从 7 条扩到 13 条（补了雾、雪、雷阵雨等）。

---

### 🟡 Bug 9：可同时开多只鱼

**原代码**：`main()` 里没有任何互斥检查。

**后果**：双击两次快捷方式 → **桌面上两三只鱼**，而且它们**抢同一个 `config.json`**，后写的覆盖先写的。（你的机器上实测出现过 **4 个进程 = 2 只鱼**。）

**修复**：用 Win32 命名互斥体 `Global\DafeiyuPet_SingleInstance` 做单实例保护，第二次启动弹提示「大肥鱼已经在桌面上了」。
**实测**：第二次启动被正确拒绝 ✅

---

### 🟡 Bug 10：开机自启快捷方式没有图标

**原代码**：PowerShell 建快捷方式时只设了 `TargetPath`/`Arguments`/`WorkingDirectory`，**没设 `IconLocation`**。

**后果**：启动文件夹里那个快捷方式是**白纸图标**，看不出是什么。

**修复**：补 `$s.IconLocation` 和 `$s.Description`。

---

### 🟡 Bug 11：开机自启可能造成双开

**问题**：程序自建的是 `大肥鱼桌宠.lnk`，而用户可能**自己往启动文件夹丢了一个不同名的**（比如 `dafeiyu-pet.lnk`）。开机时两个快捷方式都触发 → **两只鱼**。

**修复**：
- 开启自启时**清理同目录下的别名快捷方式**（`大肥鱼桌宠.lnk` / `dafeiyu-pet.lnk` / `大肥鱼桌宠（自启）.lnk`）
- 关闭自启时**逐个删除全部别名**
- 创建后**校验文件真的生成了**（否则可能被安全软件拦截），失败则回滚开关状态

---

### 🟡 Bug 12：记事本编辑配置会丢设置

**问题**：Windows **记事本默认存成带 BOM 的 UTF-8**。原代码用 `encoding="utf-8"` 读取，BOM 会导致 `json.load` 解析失败 → 静默回退到默认值 → **你手改的配置全丢**。

**修复**：读取改用 `encoding="utf-8-sig"`（自动兼容有/无 BOM）。
**实测**：带 BOM 的文件现在能正确读取用户值 ✅

> 注：程序自己写文件**不带 BOM**（已验证首字节 `7b`），所以不会自我损坏。

---

## 四、代码质量

| # | 问题 | 修复 |
|---|---|---|
| 13 | **存在两个配置加载函数** —— 旧 `load_config()` 用裸相对路径 `open("config.json")`，只在 CWD 恰好是程序目录时才工作，且返回 `{"city": "汕头"}` **只有 1 个键**（配上 Bug 1 就必崩） | 删除旧函数，统一用 `load_json(CONFIG_PATH, DEFAULTS)` |
| 14 | **裸 `except:`**（`except:` 吞掉包括 KeyboardInterrupt 在内的所有异常） | 收窄为 `except Exception:` |
| 15 | **API 错误处理假设响应是 JSON** —— 代理返回 HTML 或 502 时 `resp.json()` 抛异常，错误提示丢失 | 加 `try/except ValueError`，回退到 `HTTP {status}` |
| 16 | **调试 print 残留** 9 处，含 `print(r.text[:500])` 打印整个天气响应 | 删除无意义的（`print("输入框结果:")`、`print("cfg现在:")`、`print(r.text[:500])`），保留错误日志 |
| 17 | **`quit_app` 用 `indent=2`**，与其它地方的 `indent=4` 不一致 | 统一走 `save_json` |
| 18 | **`_apply_passthrough` 重复 `GetWindowLongPtrW` 语义** —— 每次调用都重新读一次样式 | 保留（行为正确），但补了注释说明为何置顶后要重应用 |
| 19 | **`pynvml` 已废弃**，每次启动打印 FutureWarning | 尝试先导入 `nvidia_ml_py`，减少警告噪音 |

---

## 五、验证结果

### 配置逻辑单元测试（4 项全过）
```
[TEST 1] 缺键配置自动补齐         keys missing: none          PASS
[TEST 2] 损坏配置回退并自修复     fell back + repaired        PASS
[TEST 3] 配置文件不存在时创建     created + all keys          PASS
[TEST 4] 原子保存不留 .tmp        saved + no tmp              PASS
```

### BOM 兼容测试
```
[Python 无 BOM]  city=Beijing  size=0.9   PASS（用户值保留）
[记事本 有 BOM]  city=Beijing             PASS（修复后）
[程序自己写]     首字节 7b0d0a，无 BOM    PASS
```

### 运行时测试
```
语法编译              通过
启动                 2 个进程（1 父 + 1 子）正常
单实例保护           第二次启动被拒绝      PASS
```

### 修复点自动核对
**19/19 全部到位**

---

## 六、如何回滚

```powershell
cd D:\Tools\dafeiyu-pet
Copy-Item 桌宠.py.orig 桌宠.py -Force
```

---

## 七、给作者的建议（如果想提 PR）

按价值排序：

1. **配置改为「改即保存」** —— 这是最容易让用户丢设置的坑（Bug 2）
2. **`load_json` 合并默认值** —— 一行 `data.update(loaded)` 就能避免一类崩溃（Bug 1）
3. **单实例保护** —— 多开会导致配置互相覆盖（Bug 9）
4. **网络请求全部移出主线程** —— 天气那个卡 10 秒很明显（Bug 8）
5. **`setWindowFlag` 后重应用 `WS_EX_TRANSPARENT`** —— 否则穿透会莫名失效（Bug 3）

前两条改动量极小、收益最大。
