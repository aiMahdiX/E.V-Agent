import subprocess
import json

def get_disk_status():
    """گزارش وضعیت دیسک‌ها"""
    
    # استفاده از df برای نمایش فضای دیسک
    try:
        result = subprocess.run(['df'], capture_output=True, text=True)
        df_output = result.stdout
        
        # استفاده از lsblk برای نمایش جزئیات بیشتر
        result2 = subprocess.run(['lsblk'], capture_output=True, text=True)
        lsblk_output = result2.stdout
        
        return {
            'df': df_output,
            'lsblk': lsblk_output
        }
    except Exception as e:
        return str(e)

if __name__ == "__main__":
    status = get_disk_status()
    
    print("=" * 50)
    print("گزارش وضعیت دیسک")
    print("=" * 50)
    print("\n" + status['df'])
    print("\n" + status['lsblk'])
    print("=" * 50)
