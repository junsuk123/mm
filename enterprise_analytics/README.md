# Enterprise Analytics Exports

기업 제출용 익명화 분석 파일을 저장하는 전용 디렉터리입니다.

모든 생성·검증·조회·압축·삭제 작업은 Linux CLI 진입점인
`scripts/enterprise_data.sh`를 사용합니다.

추천이 완료되면 다음 경로가 자동 생성됩니다.

```text
enterprise_analytics/
  sessions/
    <세션ID>/
      analysis_summary.json
      participants_anonymized.csv
      groups.csv
      recommendations.csv
      release_manifest.json
      SUBMISSION_README.md
```

참가자 이름·별명, 원본 사용자 ID, 기기 UUID, QR 접속 URL, 참가자 위치
좌표는 내보내지 않습니다. 익명 ID는 각 패키지 안에서 `P001`부터 새로
부여되며 운영 ID와의 매핑 파일은 생성하지 않습니다.

기존 추천 결과 JSON을 직접 변환할 수도 있습니다.

```bash
sh scripts/enterprise_data.sh export \
  --input /tmp/session_SESSION_ID_result.json \
  --session-id SESSION_ID
```

## 가이드

- [활용성과 사용 방법](USAGE_GUIDE.md)
- [CLI 운영](CLI_GUIDE.md)
- [데이터 사전](DATA_DICTIONARY.md)
- [준수사항](COMPLIANCE_GUIDE.md)
- [상업화 모델](COMMERCIALIZATION_GUIDE.md)
