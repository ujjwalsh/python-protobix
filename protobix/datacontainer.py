import re
import time
import configobj
import logging
import warnings, functools
try: import simplejson as json
except ImportError: import json
from datetime import datetime

from .zabbixagentconfig import ZabbixAgentConfig

from .senderprotocol import SenderProtocol

# For both 2.0 & >2.2 Zabbix version
# ? 1.8: Processed 0 Failed 1 Total 1 Seconds spent 0.000057
# 2.0: Processed 0 Failed 1 Total 1 Seconds spent 0.000057
# 2.2: processed: 50; failed: 1000; total: 1050; seconds spent: 0.09957
# 2.4: processed: 50; failed: 1000; total: 1050; seconds spent: 0.09957
ZBX_RESP_REGEX = r'[Pp]rocessed:? (\d+);? [Ff]ailed:? (\d+);? [Tt]otal:? (\d+);? [Ss]econds spent:? (\d+\.\d+)'
ZBX_DBG_SEND_RESULT = "Send result [%s-%s-%s] for %s"
ZBX_DBG_SEND_ITEM   = "[%s %s %s]"
ZBX_SEND_ITEM   = "[%d items]"

class DataContainer(SenderProtocol):

    _data_type = None
    _items_list = []

    def __init__(self, data_type  = None,
                       zbx_file   = '/etc/zabbix/zabbix_agentd.conf',
                       zbx_host   = None,
                       zbx_port   = None,
                       log_level  = None,
                       log_output = None,
                       dryrun     = False,
                       logger     = None):

        super(DataContainer,self).__init__()

        # Loads config from zabbix_agentd file
        # If no file, it uses the default _config as configuration
        self._zbx_config = ZabbixAgentConfig(zbx_file)
        self._pbx_config = {
            'dryrun': False,
            'data_type': None
        }
        # Override default values with the ones provided
        if log_level:
            self._zbx_config.debug_level = log_level
        if log_output != None:
            self._zbx_config.log_file = log_output
        self._pbx_config['dryrun'] = dryrun
        if zbx_host:
            self._zbx_config.server_active = zbx_host
        if zbx_port:
            self._zbx_config.server_port = zbx_port
        if data_type:
            self._pbx_config['data_type'] = data_type
        self._logger = logger

    @property
    def data_type(self):
        return self._pbx_config['data_type']

    @data_type.setter
    def data_type(self, value):
        if self._logger:
            self._logger.debug("Setting value %s as data_type" % value)
        if value in ['lld', 'items']:
          self._pbx_config['data_type'] = value
          # Clean _items_list & _result when changing _data_type
          # Incompatible format
          self._items_list = []
          self._result = []
        else:
            if self._logger:
                self._logger.error('data_type requires either "items" or "lld"')
            raise ValueError('data_type requires either "items" or "lld"')

    @property
    def logger(self):
        return self._logger

    @logger.setter
    def logger(self, value):
        if isinstance(value, logging.Logger):
            self._logger = value
        else:
            if self._logger:
                self._logger.error('logger requires a logging instance')
            raise ValueError('logger requires a logging instance')

    @property
    def log_output(self):
        return self._pbx_config['log_output']

    def add_item(self, host, key, value, clock=None):
        if clock is None:
            clock = self.clock
        if self._pbx_config['data_type'] == "items":
            item = { "host": host, "key": key,
                     "value": value, "clock": clock}
        elif self._pbx_config['data_type'] == "lld":
            item = { "host": host, "key": key, "clock": clock,
                     "value": json.dumps({"data": value}) }
        else:
            if self._logger:
                self._logger.error('Setup data_type before adding data')
            raise ValueError('Setup data_type before adding data')
        self._items_list.append(item)

    def add(self, data):
        for host in data:
            for key in data[host]:
                if not data[host][key] == []:
                    self.add_item( host, key, data[host][key])

    def send(self):
        zbx_answer = 0
        self._result = []
        if self._zbx_config.debug_level >= 4:
            # Per item sent if debug mode enabled
            for item in self._items_list:
                output =  ZBX_DBG_SEND_ITEM % (
                    item["host"],
                    item["key"],
                    item["value"]
                )
                zbx_answer = self._send_to_zabbix(item)
                result = self._handle_response(zbx_answer, output)
                if self.logger:
                    self.logger.debug(
                        ZBX_DBG_SEND_RESULT % (
                            result[0],
                            result[1],
                            result[2],
                            output
                        )
                    )
                self._result.append(result)
        else:
            # All items at once if no debug
            output = ZBX_SEND_ITEM % (
                len(self._items_list)
            )
            zbx_answer = self._send_to_zabbix(self._items_list)
            result = self._handle_response(zbx_answer, output)
            if self.logger:
                self.logger.info(
                    ZBX_DBG_SEND_RESULT % (
                        result[0],
                        result[1],
                        result[2],
                        output
                    )
                )
            self._result.append(result)
        self.data = None
        self._items_list = []
        if not self._pbx_config['dryrun']:
            self.zbx_sock.close()
        self._pbx_config['data_type'] = None

    def _handle_response(self, zbx_answer, output):
        if zbx_answer and self.logger:
            self.logger.debug("Got [%s] as response from Zabbix server" % zbx_answer)
        nb_item = len(self._items_list)
        if self._zbx_config.debug_level >= 4:
            nb_item = 1
        if zbx_answer:
            if zbx_answer.get('response') == 'success':
                result = re.findall( ZBX_RESP_REGEX, zbx_answer.get('info'))
                result = result[0]
        else:
            result = ['d', 'd', str(nb_item)]
        return result
