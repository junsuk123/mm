# 기업 데이터 Linux CLI 운영 가이드

기업 제출용 데이터의 생성과 관리는 다음 단일 진입점을 사용합니다.

```bash
sh scripts/enterprise_data.sh --help
```

## 생성

```bash
sh scripts/enterprise_data.sh export \
  --input /tmp/session_SESSION_ID_result.json \
  --session-id SESSION_ID
```

웹과 그룹 CLI 추천은 추천 완료 후 위 명령을 자동 호출합니다.

## 목록

```bash
sh scripts/enterprise_data.sh list
```

## 요약 조회

```bash
sh scripts/enterprise_data.sh inspect SESSION_ID
```

원본 참가자 ID나 이름을 출력하지 않고 세션·집계·그룹 요약만 `jq`로 표시합니다.

## 무결성·개인정보 필드 검사

```bash
sh scripts/enterprise_data.sh verify SESSION_ID

# 모든 세션
sh scripts/enterprise_data.sh verify
```

필수 파일, JSON 스키마 핵심 항목, 외부 제공 후보 파일의 식별자 필드 포함 여부를 검사합니다.

## 외부 전달용 압축

```bash
sh scripts/enterprise_data.sh archive SESSION_ID
```

기본 압축은 다음 외부 제공 후보만 포함합니다.

- `analysis_summary.json`
- `groups.csv`
- `recommendations.csv`
- `release_manifest.json`
- `SUBMISSION_README.md`

`participants_anonymized.csv`는 포함하지 않습니다.

법률·보안 검토가 완료된 제한 자료까지 압축하려면 두 개의 명시적 확인 옵션이 필요합니다.

```bash
sh scripts/enterprise_data.sh archive SESSION_ID \
  --include-restricted \
  --confirm-legal-review
```

압축 파일과 SHA-256 파일은 `enterprise_analytics/archives/`에 저장됩니다.

```bash
sha256sum -c enterprise_analytics/archives/FILE.tar.gz.sha256
```

## 삭제

```bash
sh scripts/enterprise_data.sh delete SESSION_ID --yes
```

삭제 전에 기본 외부 전달용 압축과 검증 로그를 보관할지 확인하세요. 삭제는 복구되지 않습니다.

## 운영 원칙

- 운영 원본인 `dataset/`을 외부 전달 폴더로 복사하지 않습니다.
- 외부 전달은 항상 `archive` 기본 명령 결과를 사용합니다.
- 제한 자료 압축 옵션은 법률·보안 검토 기록이 있을 때만 사용합니다.
- 전달 일시, 수신 법인, 담당자, 계약 번호, 파일 SHA-256과 폐기 예정일을 별도 대장에 기록합니다.
