# XEROX_MODS — Free Fire Friend Request API

A Flask-based Free Fire utility API designed to process friend-request operations using configured account credentials, regional servers, JWT authentication, and player-information APIs.

---

## 📌 Source Information

* **Source Creator:** [XEROX_MODS](https://t.me/XEROX_MODS)
* **Telegram Channel:** [SEXTYMODS](https://t.me/SEXTYMODS)

> **Important:** Please do not remove, modify, hide, or replace the original creator credit when using, modifying, or sharing this source.

---

## 🚀 Features

* Flask REST API
* Free Fire regional server support
* Multiple region configuration
* Account loading from text files
* Automatic JWT token retrieval
* Background JWT token refresh
* Cached JWT tokens for accounts
* Player information lookup
* Friend-request processing
* Multi-threaded account processing
* Health/status endpoint
* Region-specific account files
* Configurable request count
* JSON API responses
* Basic request error handling

---

## 🌍 Supported Regions

The source currently contains configuration for the following regions:

| Region Code | Server Name |
| :--- | :--- |
| **IND** | India |
| **ME** | Middle East |
| **VN** | Vietnam |
| **BD** | Bangladesh |
| **PK** | Pakistan |
| **SG** | Singapore |
| **BR** | Brazil |
| **NA** | North America |
| **ID** | Indonesia |
| **RU** | Russia |
| **TH** | Thailand |

---

## 📁 Project Structure

```text
project/
│
├── main.py
├── byte.py
├── accounts.txt
│
├── Account_ind.txt
├── Account_me.txt
├── Account_vn.txt
├── Account_bd.txt
├── Account_pk.txt
├── Account_sg.txt
├── Account_br.txt
├── Account_na.txt
├── Account_id.txt
├── Account_ru.txt
├── Account_th.txt
│
└── README.md
```

> *Note:* `main.py` represents the main Flask application in this example. If your Python file has another name, replace it accordingly.

---

## 📦 Requirements

Make sure Python is installed on your system [cite: 16].

### Required Python Packages [cite: 16]:
* `requests` [cite: 16]
* `pycryptodome` [cite: 16]
* `flask` [cite: 16]
* `urllib3` [cite: 16]

### Installation Command [cite: 16]:
```bash
# pip install requests pycryptodome flask urllib3
```

---

## ⚙️ Account Configuration

The source reads UID and password combinations from account files.

### Format (`accounts.txt`):
```text
UID:PASSWORD
UID:PASSWORD
UID:PASSWORD
```

### Region-Specific Files:
You can use dedicated files such as:
* `Account_ind.txt`
* `Account_bd.txt`
* `Account_pk.txt`

*(The application also supports variations like `accounts_ind.txt` or `Accountind.txt`)*

> **Security Note:** Keep account credentials private and do not publish them in a public repository.

---

## 🌐 Region Configuration

The application uses a region mapping similar to:

```python
REGION_MAP = {
    "ind": "...",
    "me": "...",
    "vn": "...",
    "bd": "...",
    "pk": "...",
    "sg": "...",
    "br": "...",
    "na": "...",
    "id": "...",
    "ru": "...",
    "th": "...",
}
```

---

## 🔑 JWT Authentication

* The source obtains JWT tokens through the configured external JWT API.
* Tokens are stored in memory using the account UID as the key: `JWT_TOKEN = {}`
* If a token is not already cached, the application attempts to obtain a new token before processing the request.
* The background thread periodically refreshes tokens for configured accounts every **7 hours**.

---

## 👤 Player Information

The application can request player information using a configured player-information API. Returned information may include:

* Nickname
* UID
* Region
* Likes
* Prime level
* Level
* Last login
* Account creation time

*(The `/spam` response also includes basic player information when successfully retrieved.)*

---

## 🔌 API Endpoints

### 1. Health Check
* **Route:** `GET /health`
* **Description:** Checks the status of the application and displays account/token information.
* **Example URL:** `http://localhost:5000/health`
* **Sample Response:**
```json
{
    "status": "ok",
    "total_uid_password_count": 0,
    "total_cached_tokens": 0,
    "regional_tokens": {}
}
```

### 2. Friend Request / Spam Operation
* **Route:** `GET /spam`
* **Description:** Processes the configured friend-request operation for a target UID.
* **Basic Example:** `http://localhost:5000/spam?uid=123456789`
* **Advanced Options:** 
  * With count: `http://localhost:5000/spam?uid=123456789&count=5`
  * With region: `http://localhost:5000/spam?uid=123456789&count=5&region=bd`

> Use only accounts and targets that you are authorized to use, and respect the game's rules and applicable service limits.

---

## 📄 API Response Example

A successful response may contain fields similar to:

```json
{
    "Nickname": "Player",
    "Uid": "123456789",
    "Region": "IND",
    "Likes": "100",
    "Prime level": 1,
    "Successful count": 5,
    "Failed count": 0
}
```

---

## 🚀 Running the Project

Start the application with:
```bash
python main.py
```

The Flask server will start on `http://0.0.0.0:5000`. For local testing, open `http://127.0.0.1:5000/health`.

---

## 🔄 Background Token Refresh Flow

```text
Application Start
       │
       ▼
Load Account Files
       │
       ▼
Request JWT Tokens
       │
       ▼
Store Tokens In Memory
       │
       ▼
Wait Approximately 7 Hours
       │
       ▼
Refresh Tokens ──► (Repeat)
```

---

## ⚠️ Error Handling

The source includes handling for common situations such as:
* Missing UID
* Invalid region
* Missing account files
* JWT API timeout
* Invalid JWT response
* HTTP errors
* Player information API failure
* Invalid request responses
* Missing configuration files

---

## 🔒 Security Notice

Never upload the following information to a public repository:
* UIDs & Passwords
* JWT Tokens
* API Keys & Private Credentials
* Private Configurations

Use environment variables or private configuration files where appropriate.

---

## 📌 Important Usage Notice

This project depends on external services and game-related endpoints that may change without notice. The source may stop working if:
* API endpoints or server endpoints change
* Authentication requirements change
* Game updates modify request formats
* External APIs become unavailable or rate limits are introduced

---

## 🛡️ Original Credit & Attribution

```text
===============================================================
                    SOURCE CREDIT
===============================================================

This Source Was Created and Developed By: XEROX_MODS

Official Telegram Channel: SEXTYMODS

Please Do Not Remove, Edit, Hide, or Replace
The Original Creator Credit.

Creator Name  : XEROX_MODS
Telegram      : SEXTYMODS
Source Credit : XEROX_MODS

===============================================================
```

---

## ⚖️ Disclaimer & License

* **Disclaimer:** The creator does not guarantee uninterrupted operation because the project relies on external APIs and services. Users are responsible for their own use of the software, account credentials, and compliance with applicable terms.
* **License:** No separate open-source license is specified. Unless the creator explicitly grants permission, do not commercially redistribute or relicense this source.

---