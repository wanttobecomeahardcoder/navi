# NAVI
## full local open source voice assistent for COSMIC DE

---
## ⚖️ disclaimer

this project was inspired by the anime **Serial Experiments Lain**. however, it is an independent, fan-made project and is <u>not affiliated</u> with, authorized, maintained, sponsored, or endorsed by the original creators, authors, production studios, or any of their affiliates. all trademarks and copyrights belong to their respective owners.

---
##  ⚠️ whisper model setup

the whisper model files are split into parts due to github size limits. after cloning the repository, assemble the original model file by running this command in your terminal:


```bash
cat models/whisper/model.bin.part* > models/whisper/model.bin
```

after successful assembly, you can safely delete the .part* files to save space

---
## ⚠️ localization

english localization is not yet supported. the voice assistant currently only recognizes russian speech.

---
## ⚙️ aliases, dictionary and custom commands:

| file name(`support_files/...`) | usability                                                                                        | var 1                      | var 2                         | exemple                          |
|:-------------------------------|:-------------------------------------------------------------------------------------------------|:---------------------------|:------------------------------|:---------------------------------|
| `aliases.txt`                  | helps give an alternative, more convenient name to an application                                | alias                      | real app name                 | `tg : telegram`                  |
| `dictionary.txt`               | stores text replies or website links triggered when the voice assistant hears a specific keyword | keyword heard by assistant | text to output or URL to open | `youtube : https://youtube.com`  |
| `custom_commands.txt`          | stores custom terminal/console commands                                                          | command name               | Bash command                  | `sleep : sudo systemctl suspend` |
| `name.txt`                     | contains only a single line with your name, nothing extra                                        | name                       | —                             | `sir`                            |

---
# 📝 note: 

the frontend was built using chatGPT

---
# ☕ support the author

if you like this voice assistant and want to support its development, you can buy me a can of energy drink! any support is greatly appreciated.

#### **boosty:** `https://boosty.io/wanttobecomeahardcoder/about`
#### **crypto (USDT TRC-20):** `TY6DtKF3vud9dR21TCniVNSZXEnDjjkLYD`

---

