# Alert Bot 0.6.0

감시 상태는 running / recovering / paused입니다. stop Event는 프로그램 종료·예약 종료용이며 수동 감시 중지는 paused로 처리합니다. 명령 polling은 대기 중에도 유지합니다.

자동 복구는 5초 유휴 확인 → 원래 EMR 창 복원/활성화 → 입력 기준 설정 → foreground·크기·가림 검증 → 캡처 → 표 영역 재확인 순서입니다. 기존 비교 baseline과 예약 종료 deadline은 유지합니다. 수동 stop은 자동 복구를 차단합니다.

명령을 보낸 그룹과 봇 suffix를 검증하고 update offset으로 중복을 막습니다. 전송 재시도 중에도 명령을 확인합니다. 사용자 입력 watchdog과 EMR 조작은 공통 lock으로 보호합니다.

가림 검사에서 정확히 등록된 자체 테두리 핸들만 제외합니다. 다른 창은 계속 차단합니다. 크기·대상 식별 변화는 자동 복구가 아닌 수동 대기로 전환합니다.
