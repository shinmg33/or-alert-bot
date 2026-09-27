# Alert Bot 0.8.0

감시 상태는 running / recovering / paused입니다. stop Event는 프로그램 종료·예약 종료용이며 수동 감시 중지는 paused로 처리합니다. 명령 polling은 대기 중에도 유지합니다.

자동 복구는 5초 유휴 확인 → 원래 EMR 창 복원/활성화 → 입력 기준 설정 → foreground·크기·가림 검증 → 캡처 → 표 영역 재확인 순서입니다. 기존 비교 baseline과 예약 종료 deadline은 유지합니다. 수동 stop은 자동 복구를 차단합니다.

명령을 보낸 그룹과 봇 suffix를 검증하고 update offset으로 중복을 막습니다. 전송 재시도 중에도 명령을 확인합니다. 사용자 입력 watchdog과 EMR 조작은 공통 lock으로 보호합니다.

가림 검사에서 정확히 등록된 자체 테두리 핸들만 제외합니다. 다른 창은 계속 차단합니다. 크기·대상 식별 변화는 자동 복구가 아닌 수동 대기로 전환합니다.

critical_regions는 조회 버튼, 격자에서 찾은 현재 머리글/행, 전송 캡처 범위입니다. 캡처 후 새 범위에 대한 가림 검사를 다시 수행합니다. 전체 창 foreground 조건은 critical_regions 사용 시 요구하지 않지만 입력·창 식별·크기 검증은 유지합니다. 변경 비교는 보이는 표만 사용하고, 전송은 상단 조건 및 아래 여백을 포함합니다. 자동 대기는 120초 이후 한 번만 시스템 안내로 발송합니다. 시스템 sendMessage는 기본 disable_notification=true, 목록 변경 sendDocument는 별도 설정을 사용합니다.


원격 필터 요청은 poll_commands에서 검증해 pending_filter에 한 건만 저장합니다. run 루프에서만 실행하여 표 비교·전송 중간에 EMR 입력이 끼어들지 않습니다. 날짜는 명시적 캘린더 버튼 및 제목/월 화살표/6행 격자, 진료과는 글자 영역과 아래 화살표를 각각 등록합니다. FilterControls는 로컬 OCR로 선택값을 검증하고 실패 시 수동 대기로 전환합니다. 성공 시 조회한 안정된 결과를 새 baseline으로 설정하고 캡처를 전송합니다. 팝업 허용은 달력 작업 동안만 켜며 같은 실행 파일의 대상 소유 팝업만 허용합니다.

검증: Linux에서 Windows API 진입부를 mock한 72개 로직 회귀 테스트 통과. Windows GUI·네이티브 OCR·실제 EMR 입력 및 Telegram 실전송은 이 환경에서 검증하지 않았습니다. Windows에서 build.ps1을 실행하면 전체 테스트 후 EXE를 생성합니다.
