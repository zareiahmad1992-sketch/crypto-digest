       if [ "${{ github.event.inputs.ping }}" = "true" ]; then
         python trend_alerts.py --ping
       else
         python trend_alerts.py
       fi
