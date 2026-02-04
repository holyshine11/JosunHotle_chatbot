# 조선호텔 크롤러

5개 호텔(조선팰리스, 그랜드조선부산, 그랜드조선제주, 레스케이프, 그래비티판교)의 FAQ, 정책, 객실, 다이닝, 시설 정보를 크롤링합니다.

## 사용법

```bash
# Python 3.11 사용 (pyenv)
PYTHON=~/.pyenv/versions/3.11.7/bin/python3

# 전체 호텔 크롤링 (변경된 페이지만)
$PYTHON crawler/josun_crawler.py

# 특정 호텔만 크롤링
$PYTHON crawler/josun_crawler.py --hotel josun_palace
$PYTHON crawler/josun_crawler.py --hotel grand_josun_busan
$PYTHON crawler/josun_crawler.py --hotel grand_josun_jeju
$PYTHON crawler/josun_crawler.py --hotel lescape
$PYTHON crawler/josun_crawler.py --hotel gravity_pangyo

# 강제 재크롤링 (변경 여부 무시)
$PYTHON crawler/josun_crawler.py --force
$PYTHON crawler/josun_crawler.py --hotel josun_palace --force

# 호텔 목록 확인
$PYTHON crawler/josun_crawler.py --list
```

## 파일 구조

```
crawler/
├── josun_crawler.py    # 메인 크롤러
├── seed_urls.json      # 호텔별 URL 설정
└── README.md           # 이 파일

data/
├── raw/                # 크롤링 원본 데이터
│   └── {hotel}/
│       ├── {hotel}_faq_*.json
│       ├── {hotel}_faq_*.html
│       ├── {hotel}_policy_*.json
│       └── ...
└── hash_store.json     # 증분 업데이트용 해시
```

## 크롤링 대상

| 호텔 키 | 호텔명 | 서브도메인 |
|--------|-------|-----------|
| josun_palace | 조선 팰리스 | jpg.josunhotel.com |
| grand_josun_busan | 그랜드 조선 부산 | gjb.josunhotel.com |
| grand_josun_jeju | 그랜드 조선 제주 | gjj.josunhotel.com |
| lescape | 레스케이프 | les.josunhotel.com |
| gravity_pangyo | 그래비티 판교 | grp.josunhotel.com |

## 수집 페이지

- `/about/faq.do` - FAQ
- `/policy/hotel.do` - 호텔 정책
- `/rooms/subMain.do` - 객실 정보
- `/dining/subMain.do` - 다이닝
- `/facilities/subMain.do` - 부대시설

## 증분 업데이트

- `hash_store.json`에 각 페이지의 SHA256 해시 저장
- 해시가 동일하면 크롤링 스킵
- `--force` 옵션으로 강제 재크롤링 가능

## 의존성

```bash
pip install requests beautifulsoup4 lxml
```
