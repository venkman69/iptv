import unittest
import sys
sys.path.append("/home/venkman/git/iptv")
from app.utils import compare_vods

class TestCompareVods(unittest.TestCase):

    def test_compare_vods_new_entries(self):
        old_vod = "#EXTM3U\n#EXTINF:-1,Old Channel\nhttp://oldchannel.com/stream\n"
        new_vod = "#EXTM3U\n#EXTINF:-1,Old Channel\nhttp://oldchannel.com/stream\n#EXTINF:-1,New Channel\nhttp://newchannel.com/stream\n"
        expected_result = [
            "#EXTM3U",
            "#EXTINF:-1,New Channel",
            "http://newchannel.com/stream"
        ]
        result = compare_vods(old_vod, new_vod)
        self.assertEqual(result, expected_result)

    def test_compare_vods_no_new_entries(self):
        old_vod = "#EXTM3U\n#EXTINF:-1,Old Channel\nhttp://oldchannel.com/stream\n"
        new_vod = "#EXTM3U\n#EXTINF:-1,Old Channel\nhttp://oldchannel.com/stream\n"
        expected_result = ["#EXTM3U"]
        result = compare_vods(old_vod, new_vod)
        self.assertEqual(result, expected_result)

    def test_compare_vods_multiple_new_entries(self):
        old_vod = "#EXTM3U\n#EXTINF:-1,Old Channel\nhttp://oldchannel.com/stream\n"
        new_vod = "#EXTM3U\n#EXTINF:-1,Old Channel\nhttp://oldchannel.com/stream\n#EXTINF:-1,New Channel 1\nhttp://newchannel1.com/stream\n#EXTINF:-1,New Channel 2\nhttp://newchannel2.com/stream\n"
        expected_result = [
            "#EXTM3U",
            "#EXTINF:-1,New Channel 1",
            "http://newchannel1.com/stream",
            "#EXTINF:-1,New Channel 2",
            "http://newchannel2.com/stream"
        ]
        result = compare_vods(old_vod, new_vod)
        self.assertEqual(result, expected_result)

if __name__ == '__main__':
    unittest.main()