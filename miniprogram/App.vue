<script>
import { connectWS } from '@/utils/ws'

export default {
  onLaunch() {
    // 启动后建立 WebSocket 长连接，接收实时通知
    connectWS()
  },
}
</script>

<style>
page {
  background-color: #f5f6f7;
  color: #333333;
  font-size: 28rpx;
}
</style>
