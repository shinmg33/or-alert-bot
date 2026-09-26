if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--selfcheck':
        from or_alert.selfcheck import run
        run(sys.argv[2])
    else:
        from or_alert.app import main
        main()
