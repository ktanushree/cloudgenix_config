# -*- coding: utf-8 -*-
"""
Configuration IMPORT worker/script

**Version:** 1.1.0b1

**Author:** CloudGenix

**Copyright:** (c) 2017, 2018 CloudGenix, Inc

**License:** MIT

**Location:** <https://github.com/CloudGenix/cloudgenix_config>

#### Synopsis
Meant to be a CI configuration runner, apply configuration in file and move Cloud Controller to the
state specified in the YAML File

#### Requirements
* Active CloudGenix Account
* Python >= 2.7 or >=3.6
* Python modules:
    * CloudGenix Python SDK >= 5.0.1b1 - <https://github.com/CloudGenix/sdk-python>

#### License
MIT

#### For more info
 * Get help and additional CloudGenix Documentation at <http://support.cloudgenix.com>

"""

import yaml
import json
import logging
import copy
import time
import sys
import os
import argparse

# CloudGenix Python SDK
try:
    import cloudgenix
    jdout = cloudgenix.jdout
    jd = cloudgenix.jd
except ImportError as e:
    cloudgenix = None
    sys.stderr.write("ERROR: 'cloudgenix' python module required. (try 'pip install cloudgenix').\n {0}\n".format(e))
    sys.exit(1)

# import module specific
from cloudgenix_config import throw_error, throw_warning, fuzzy_pop, config_lower_version_get, \
    config_lower_get, name_lookup_in_template, extract_items, build_lookup_dict, build_lookup_dict_snmp_trap, \
    list_to_named_key_value, recombine_named_key_value, get_default_ifconfig_from_model_string, \
    order_interface_by_number, get_member_default_config, default_backwards_bypasspairs, find_diff, \
    nameable_interface_types, skip_interface_list, CloudGenixConfigError

# Check config file, in cwd.
sys.path.append(os.getcwd())
try:
    from cloudgenix_settings import CLOUDGENIX_AUTH_TOKEN

except ImportError:
    # Get AUTH_TOKEN/X_AUTH_TOKEN from env variable, if it exists. X_AUTH_TOKEN takes priority.
    if "X_AUTH_TOKEN" in os.environ:
        CLOUDGENIX_AUTH_TOKEN = os.environ.get('X_AUTH_TOKEN')
    elif "AUTH_TOKEN" in os.environ:
        CLOUDGENIX_AUTH_TOKEN = os.environ.get('AUTH_TOKEN')
    else:
        # not set
        CLOUDGENIX_AUTH_TOKEN = None

try:
    from cloudgenix_settings import CLOUDGENIX_USER, CLOUDGENIX_PASSWORD

except ImportError:
    # will get caught below
    CLOUDGENIX_USER = None
    CLOUDGENIX_PASSWORD = None


# python 2 and 3 handling
if sys.version_info < (3,):
    text_type = unicode
    binary_type = str
else:
    text_type = str
    binary_type = bytes


__author__ = "CloudGenix Developer Support <developers@cloudgenix.com>"
__email__ = "developers@cloudgenix.com"
__copyright__ = "Copyright (c) 2017, 2018 CloudGenix, Inc"
__license__ = """
    MIT License

    Copyright (c) 2017, 2018 CloudGenix, Inc

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
"""

# Globals

# Constant settings
FILE_TYPE_REQUIRED = "cloudgenix template"
FILE_VERSION_REQUIRED = "1.0"
DEFAULT_WAIT_MAX_TIME = 600  # seconds
DEFAULT_WAIT_INTERVAL = 10  # seconds

# Const structs
element_put_items = [
    "cluster_member_id",
    "cluster_insertion_mode",
    "description",
    "site_id",
    "_schema",
    "_etag",
    "sw_obj",
    "id",
    "name",
    "l3_direct_private_wan_forwarding",
    "l3_lan_forwarding",
    "network_policysetstack_id",
    "priority_policysetstack_id",
    "spoke_ha_config",
    "tags"
]

createable_interface_types = [
    'pppoe',
    'subinterface',
    'loopback',
    'service_link',
    'bypasspair'
]

bypasspair_child_names = [
    "wan 1",
    "lan 1",
    "wan 2",
    "lan 2",
    "wan 3",
    "lan 3",
    "wan 4",
    "lan 4",
    "internet 1",
    "internet bypass 1",
    "internet 2",
    "internet bypass 2",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "10",
    "11",
    "12",
    "13"
]

# Global Config Cache holders
sites_cache = []
elements_cache = []
machines_cache = []
policysets_cache = []
security_policysets_cache = []
securityzones_cache = []
network_policysetstack_cache = []
priority_policysetstack_cache = []
waninterfacelabels_cache = []
wannetworks_cache = []
wanoverlays_cache = []
servicebindingmaps_cache = []
serviceendpoints_cache = []
ipsecprofiles_cache = []
networkcontexts_cache = []
appdefs_cache = []
sites_n2id = {}
elements_n2id = {}
policysets_n2id = {}
security_policysets_n2id = {}
securityzones_n2id = {}
network_policysetstack_n2id = {}
priority_policysetstack_n2id = {}
waninterfacelabels_n2id = {}
wannetworks_n2id = {}
wanoverlays_n2id = {}
servicebindingmaps_n2id = {}
serviceendpoints_n2id = {}
ipsecprofiles_n2id = {}
networkcontexts_n2id = {}
appdefs_n2id = {}
elements_byserial = {}
machines_byserial = {}
securityzones_id2n = {}

# global configurable items
timeout_offline = DEFAULT_WAIT_MAX_TIME
timeout_claim = DEFAULT_WAIT_MAX_TIME
timeout_upgrade = DEFAULT_WAIT_MAX_TIME
wait_upgrade = True
timeout_state = DEFAULT_WAIT_MAX_TIME
interval_timeout = DEFAULT_WAIT_INTERVAL
force_update = False
site_safety_factor = 1

# CloudGenix SDK and JSON DUMP helper
sdk = cloudgenix.API()
jd = cloudgenix.jd

# logging
logger = logging.getLogger(__name__)
debuglevel = 1
sdk_debuglevel = 0


def local_info(message, resp=None, cr=True):
    """
    Write INFO message to stdout if apropriate debuglevel is set
    :param message: Info message
    :param resp: Optional - CloudGenix SDK response
    :param cr: add Carriage returns.
    :return: None
    """
    if debuglevel >= 2:
        output = "INFO: " + str(message)
        if cr:
            output += "\n"
        sys.stdout.write(output)
        if resp is not None:
            output2 = str(jdout(resp))
            if cr:
                output2 += "\n"
            sys.stdout.write(output2)
    return


def local_debug(message, resp=None, cr=True):
    """
    Write DEBUG message to stdout if apropriate debuglevel is set
    :param message: Debug message
    :param resp: Optional - CloudGenix SDK response
    :param cr: add Carriage returns.
    :return: None
    """
    if debuglevel >= 3:
        output = "DEBUG: " + str(message)
        if cr:
            output += "\n"
        sys.stdout.write(output)
        if resp is not None:
            output2 = str(jdout(resp))
            if cr:
                output2 += "\n"
            sys.stdout.write(output2)
    return


def output_message(message, resp=None, cr=True):
    """
    Output message to STDOUT. Replacement for print.
    :param message: Message to print
    :param resp: Optional - CloudGenix SDK response
    :param cr: add Carriage returns.
    :return: None
    """
    if debuglevel >= 1:
        output = str(message)
        if cr:
            output += "\n"
        sys.stdout.write(output)
        if resp is not None:
            output2 = str(jdout(resp))
            if cr:
                output2 += "\n"
            sys.stdout.write(output2)
    return


def update_global_cache():
    """
    Update Cache of Global objects (not Site or Element Specific)
    :return: No Return, mutates global objects in-place.
    """
    global sites_cache
    global elements_cache
    global machines_cache
    global policysets_cache
    global security_policysets_cache
    global securityzones_cache
    global network_policysetstack_cache
    global priority_policysetstack_cache
    global waninterfacelabels_cache
    global wannetworks_cache
    global wanoverlays_cache
    global servicebindingmaps_cache
    global serviceendpoints_cache
    global ipsecprofiles_cache
    global networkcontexts_cache
    global appdefs_cache
    global sites_n2id
    global elements_n2id
    global policysets_n2id
    global security_policysets_n2id
    global securityzones_n2id
    global network_policysetstack_n2id
    global priority_policysetstack_n2id
    global waninterfacelabels_n2id
    global wannetworks_n2id
    global wanoverlays_n2id
    global servicebindingmaps_n2id
    global serviceendpoints_n2id
    global ipsecprofiles_n2id
    global networkcontexts_n2id
    global appdefs_n2id
    global elements_byserial
    global machines_byserial
    global securityzones_id2n

    # sites
    sites_resp = sdk.get.sites()
    sites_cache, _ = extract_items(sites_resp, 'sites')

    # elements
    elements_resp = sdk.get.elements()
    elements_cache, _ = extract_items(elements_resp, 'elements')

    # machines
    machines_resp = sdk.get.machines()
    machines_cache, _ = extract_items(machines_resp, 'machines')

    # policysets
    policysets_resp = sdk.get.policysets()
    policysets_cache, _ = extract_items(policysets_resp, 'policysets')

    # secuirity_policysets
    security_policysets_resp = sdk.get.securitypolicysets()
    security_policysets_cache, _ = extract_items(security_policysets_resp, 'security_policysets')

    # secuirityzones
    securityzones_resp = sdk.get.securityzones()
    securityzones_cache, _ = extract_items(securityzones_resp, 'securityzones')

    # network_policysetstack
    network_policysetstack_resp = sdk.get.networkpolicysetstacks()
    network_policysetstack_cache, _ = extract_items(network_policysetstack_resp, 'network_policysetstack')

    # prioroty_policysetstack
    priority_policysetstack_resp = sdk.get.prioritypolicysetstacks()
    priority_policysetstack_cache, _ = extract_items(priority_policysetstack_resp, 'prioroty_policysetstack')

    # waninterfacelabels
    waninterfacelabels_resp = sdk.get.waninterfacelabels()
    waninterfacelabels_cache, _ = extract_items(waninterfacelabels_resp, 'waninterfacelabels')

    # wannetworks
    wannetworks_resp = sdk.get.wannetworks()
    wannetworks_cache, _ = extract_items(wannetworks_resp, 'wannetworks')

    # wanoverlays
    wanoverlays_resp = sdk.get.wanoverlays()
    wanoverlays_cache, _ = extract_items(wanoverlays_resp, 'wanoverlays')

    # servicebindingmaps
    servicebindingmaps_resp = sdk.get.servicebindingmaps()
    servicebindingmaps_cache, _ = extract_items(servicebindingmaps_resp, 'servicebindingmaps')

    # serviceendpoints
    serviceendpoints_resp = sdk.get.serviceendpoints()
    serviceendpoints_cache, _ = extract_items(serviceendpoints_resp, 'serviceendpoints')

    # ipsecprofiles
    ipsecprofiles_resp = sdk.get.ipsecprofiles()
    ipsecprofiles_cache, _ = extract_items(ipsecprofiles_resp, 'ipsecprofiles')

    # networkcontexts
    networkcontexts_resp = sdk.get.networkcontexts()
    networkcontexts_cache, _ = extract_items(networkcontexts_resp, 'networkcontexts')

    # appdef
    appdefs_resp = sdk.get.appdefs()
    appdefs_cache, _ = extract_items(appdefs_resp, 'appdefs')

    # sites name
    sites_n2id = build_lookup_dict(sites_cache)

    # element name
    elements_n2id = build_lookup_dict(elements_cache)

    # policysets name
    policysets_n2id = build_lookup_dict(policysets_cache)

    # security_policysets name
    security_policysets_n2id = build_lookup_dict(security_policysets_cache)

    # securityzones name
    securityzones_n2id = build_lookup_dict(securityzones_cache)

    # network_policysetstack name
    network_policysetstack_n2id = build_lookup_dict(network_policysetstack_cache)

    # prioroty_policysetstack name
    priority_policysetstack_n2id = build_lookup_dict(priority_policysetstack_cache)

    # waninterfacelabels name
    waninterfacelabels_n2id = build_lookup_dict(waninterfacelabels_cache)

    # wannetworks name
    wannetworks_n2id = build_lookup_dict(wannetworks_cache)

    # wannetworks name
    wanoverlays_n2id = build_lookup_dict(wanoverlays_cache)

    # servicebindingmaps name
    servicebindingmaps_n2id = build_lookup_dict(servicebindingmaps_cache)

    # serviceendpoints name
    serviceendpoints_n2id = build_lookup_dict(serviceendpoints_cache)

    # ipsecprofiles name
    ipsecprofiles_n2id = build_lookup_dict(ipsecprofiles_cache)

    # networkcontexts name
    networkcontexts_n2id = build_lookup_dict(networkcontexts_cache)

    # appdefs name
    appdefs_n2id = build_lookup_dict(appdefs_cache)

    # element by serial
    elements_byserial = list_to_named_key_value(elements_cache, 'serial_number', pop_index=False)

    machines_byserial = list_to_named_key_value(machines_cache, 'sl_no', pop_index=False)

    # id to name for security zones
    securityzones_id2n = build_lookup_dict(securityzones_cache, key_val='id', value_val='name')

    return


def update_element_machine_cache():
    """
    Update Cache of Element and Machine objects seperate from global update.
    :return: No Return, mutates global objects in-place.
    """
    global elements_cache
    global machines_cache
    global elements_n2id
    global elements_byserial
    global machines_byserial

    # elements
    elements_resp = sdk.get.elements()
    elements_cache, _ = extract_items(elements_resp, 'elements')

    # machines
    machines_resp = sdk.get.machines()
    machines_cache, _ = extract_items(machines_resp, 'machines')

    # element name
    elements_n2id = build_lookup_dict(elements_cache)

    # element by serial
    elements_byserial = list_to_named_key_value(elements_cache, 'serial_number', pop_index=False)

    machines_byserial = list_to_named_key_value(machines_cache, 'sl_no', pop_index=False)

    return


def parse_root_config(data_file):
    """
    Parse root of config file, verify header, extract sites and return
    :param data_file: Root dict loaded from YAML file.
    :return: Site configuration dict
    """
    # Verify template.
    yml_type = str(config_lower_get(data_file, 'type'))
    yml_ver = str(config_lower_get(data_file, 'version'))

    detect_msg = {
            "Expected Type": FILE_TYPE_REQUIRED,
            "Read Type": yml_type,
            "Expected Version": FILE_VERSION_REQUIRED,
            "Read Version": yml_ver
        }

    local_debug("CONFIG METADATA READ: " + str(json.dumps(detect_msg, indent=4)))

    if not yml_type == FILE_TYPE_REQUIRED or not yml_ver == FILE_VERSION_REQUIRED:
        throw_error("YAML file not correct type or version: ", detect_msg)

    # grab sites
    config_sites, _ = config_lower_version_get(data_file, 'sites', sdk.put.sites, default={})

    local_debug("FULL CONFIG: " + str(json.dumps(config_sites, indent=4)))

    return config_sites


def parse_site_config(config_site):
    """
    Parse Site level configuration
    :param config_site: Site config dict
    :return: Tuple of WAN Interface config, LAN Network config, Element Config, DHCP Server config, and
             Site Extension config
    """
    local_debug("SITE CONFIG: " + str(json.dumps(config_site, indent=4)))

    config_lannetworks, _ = config_lower_version_get(config_site, 'lannetworks', sdk.put.lannetworks, default={})
    config_elements, _ = config_lower_version_get(config_site, 'elements', sdk.put.elements, default={})
    config_waninterfaces, _ = config_lower_version_get(config_site, 'waninterfaces', sdk.put.waninterfaces, default={})
    config_dhcpservers, _ = config_lower_version_get(config_site, 'dhcpservers', sdk.put.dhcpservers, default=[])
    config_site_extensions, _ = config_lower_version_get(config_site, 'site_extensions',
                                                         sdk.put.site_extensions, default={})
    config_site_security_zones, _ = config_lower_version_get(config_site, 'site_security_zones',
                                                             sdk.put.sitesecurityzones, default=[])
    config_spokeclusters, _ = config_lower_version_get(config_site, 'spokeclusters', sdk.put.spokeclusters, default={})

    return config_waninterfaces, config_lannetworks, config_elements, config_dhcpservers, config_site_extensions, \
        config_site_security_zones, config_spokeclusters


def parse_element_config(config_element):
    """
    Parse Element level configuration
    :param config_element: Element config dict
    :return: Tuple of Interface config, Routing config, Syslog config, NTP config, SNMP config, Toolkit config and
             Element Extensions config
    """
    local_debug("ELEMENT CONFIG: " + str(json.dumps(config_element, indent=4)))

    config_interfaces, _ = config_lower_version_get(config_element, 'interfaces', sdk.put.interfaces, default={})
    config_routing = config_lower_get(config_element, 'routing', default={})
    config_syslog, _ = config_lower_version_get(config_element, 'syslog', sdk.put.syslogservers, default=[])
    config_ntp, _ = config_lower_version_get(config_element, 'ntp', sdk.put.ntp, default=[])
    config_snmp = config_lower_get(config_element, 'snmp', default={})
    config_toolkit, _ = config_lower_version_get(config_element, 'toolkit', sdk.put.elementaccessconfigs, default={})
    config_element_extensions, _ = config_lower_version_get(config_element, 'element_extensions',
                                                            sdk.put.element_extensions, default={})
    config_element_security_zones, _ = config_lower_version_get(config_element, 'element_security_zones',
                                                                sdk.put.elementsecurityzones, default=[])

    return config_interfaces, config_routing, config_syslog, config_ntp, config_snmp, config_toolkit, \
        config_element_extensions, config_element_security_zones


def parse_routing_config(config_routing):
    """
    Parse Routing level configuration
    :param config_routing: Routing config dict
    :return: Tuple of AS-Path ACL config, IP-Community List config, PrefixList Config, RouteMap Config,
                Static Routing config, and BGP config.
    """
    local_debug("ROUTING CONFIG: " + str(json.dumps(config_routing, indent=4)))

    config_routing_aspathaccesslists, _ = config_lower_version_get(config_routing, 'as_path_access_lists',
                                                                   sdk.put.routing_aspathaccesslists, default={})
    config_routing_ipcommunitylists, _ = config_lower_version_get(config_routing, 'ip_community_lists',
                                                                  sdk.put.routing_ipcommunitylists, default={})
    config_routing_prefixlists, _ = config_lower_version_get(config_routing, 'prefix_lists',
                                                             sdk.put.routing_prefixlists, default={})
    config_routing_routemaps, _ = config_lower_version_get(config_routing, 'route_maps',
                                                           sdk.put.routing_routemaps, default={})
    config_routing_static, _ = config_lower_version_get(config_routing, 'static', sdk.put.staticroutes, default=[])
    config_routing_bgp = config_lower_get(config_routing, 'bgp', default={})

    return config_routing_aspathaccesslists, config_routing_ipcommunitylists, config_routing_prefixlists, \
        config_routing_routemaps, config_routing_static, config_routing_bgp


def parse_bgp_config(config_routing_bgp):
    """
    Parse BGP level configuration
    :param config_routing_bgp: BGP config dict
    :return: Tuple of BGP Global config (bgpconfig) and BGP Peer configuration
    """
    local_debug("BGP CONFIG: " + str(json.dumps(config_routing_bgp, indent=4)))

    config_routing_bgp_global, _ = config_lower_version_get(config_routing_bgp, 'global_config',
                                                            sdk.put.bgpconfigs, default={})
    config_routing_bgp_peers, _ = config_lower_version_get(config_routing_bgp, 'peers',
                                                           sdk.put.bgppeers, default={})

    return config_routing_bgp_global, config_routing_bgp_peers


def parse_snmp_config(config_snmp):
    """
    Parse SNMP level config
    :param config_snmp: SNMP config dict
    :return: Tuple of SNMP Agent config, SNMP Trap config
    """
    local_debug("SNMP CONFIG: " + str(json.dumps(config_snmp, indent=4)))

    config_snmp_traps, _ = config_lower_version_get(config_snmp, 'traps', sdk.put.snmptraps, default=[])
    config_snmp_agent, _ = config_lower_version_get(config_snmp, 'agent', sdk.put.snmpagents, default=[])

    return config_snmp_agent, config_snmp_traps


def detect_elements(element_config):
    """
    Find Machine/Element items from element config
    :param element_config: Element config entry
    :return: Tuple of Serial from config, Element API match (if any), Machine API match (if any), ION model string.
    """
    config_serial = element_config.get('serial_number')
    config_name = element_config.get('name')
    config_model = element_config.get('model')

    if not config_serial:
        throw_error("No serial in element config for {0}.".format(config_name))

    # Get machine ids
    # machines_resp = sdk.get.machines()
    # machines, _ = extract_items(machines_resp, "machines")
    machines = machines_cache

    matching_machine = {}
    matching_model = None
    # get all matching machines
    for machine in machines:
        cur_machine_serial = machine.get('sl_no')
        cur_machine_model = machine.get('model_name')
        if config_serial == cur_machine_serial and cur_machine_model:
            matching_machine = machine
            matching_model = cur_machine_model

    if not matching_machine:
        throw_error("Serial number not found or allocated to tenant:", config_serial)

    # Check model if specified, autodetect if not.
    if config_model:
        if config_model != matching_model:
            throw_error("Hardcoded model for {0} does not match: "
                        "Config: {1}, Found: {2}".format(config_name,
                                                         config_model,
                                                         matching_model))
    else:
        # autodetect model
        element_config["model"] = matching_model

    elements = elements_cache

    matching_element = {}
    # get matching element if it exists
    for element in elements:
        cur_element_serial = element.get('serial_number')
        if config_serial == cur_element_serial:
            matching_element = element

    # status
    local_debug("FOUND CONFIG_SERIAL: " + str(config_serial))
    local_debug("FOUND MODEL: " + str(matching_model))
    local_debug("FOUND ELEMENT: ", matching_element)
    local_debug("FOUND MACHINE: ", matching_machine)

    return config_serial, matching_element, matching_machine, matching_model


def claim_element(matching_machine, wait_if_offline=DEFAULT_WAIT_MAX_TIME,
                  wait_verify_success=DEFAULT_WAIT_MAX_TIME, wait_interval=DEFAULT_WAIT_INTERVAL):
    """
    Perform an Element claim operation
    :param matching_machine: Machine API response for machine that will be claimed
    :param wait_if_offline: Optional - Time to wait if offline (in seconds)
    :param wait_verify_success: Optional - Time to wait for verification of success of claim (in seconds).
    :param wait_interval: Optinal - Interval to check API for updated statuses during wait.
    :return: None
    """
    # check and claim as needed.

    machine_state = "Unknown"
    machine = matching_machine
    serial = machine.get('sl_no')
    machine_id = machine.get('id')
    if not serial or not machine_id:
        throw_error("unable to get machine serial or ID:", machine)

    output_message(" Checking {0}..".format(serial))
    claimed = False
    claim_pending = False

    # Check if claimed
    machines_describe_response = sdk.get.machines(machine_id)
    if machines_describe_response.cgx_status:
        machine_state = machines_describe_response.cgx_content.get('machine_state')

        if machine_state.lower() in ['claim_pending',
                                     'manufactured_cic_issued',
                                     'manufactured_cic_issue_pending',
                                     'manufactured_cic_operational']:
            # system in process of claiming. bypass claim and wait.
            claim_pending = True

        if machine_state.lower() in ['claimed']:
            claimed = True
        else:
            claimed = False

    # if isn't claimed, begin work.
    if not claimed:

        # only verify online and claim if not in claim_pending state.
        if not claim_pending:
            output_message("  Unclaimed({0}). Beginning Claim process..".format(machine_state))
            # verify ION is online
            connected = False
            time_elapsed = 0
            while not connected:
                # check online status
                machines_describe_response = sdk.get.machines(machine_id)
                if machines_describe_response.cgx_status:
                    connected = machines_describe_response.cgx_content.get('connected', False)

                if time_elapsed > wait_if_offline:
                    throw_error("ION {0} Offline for longer than {1} seconds. Exiting."
                                "".format(serial, wait_if_offline))

                if not connected:
                    output_message("  ION {0} Offline, waited so far {1} seconds out of {2}."
                                   "".format(serial, time_elapsed, wait_if_offline))
                    time.sleep(wait_interval)
                    time_elapsed += wait_interval

            # Got here, means ION is online.
            # cgx Machine template
            machines_claim = {
                "inventory_op": "claim"
            }

            # Attempt to claim Machine
            machines_claim_response = sdk.post.tenant_machine_operations(machine_id, machines_claim)

            if not machines_claim_response.cgx_status:
                throw_error("Machine '{0}' CLAIM failed.", machines_claim_response.cgx_content)
        else:
            output_message("  Claim already in process ({0})..".format(machine_state))
        # wait and make sure that the ION moves to "claimed" state.
        time_elapsed = 0

        while not claimed:
            # check online status
            machines_describe_response = sdk.get.machines(machine_id)
            if machines_describe_response.cgx_status:
                machine_state = machines_describe_response.cgx_content.get('machine_state')
                # Update claimed
                if machine_state.lower() in ['claimed']:
                    claimed = True
                else:
                    claimed = False

            if time_elapsed > wait_verify_success:
                # failed waiting.
                throw_error("ION {0} Claim took longer than {1} seconds. Exiting."
                            "".format(serial, wait_verify_success))

            if not claimed:
                output_message("  ION {0} still claiming, waited so far {1} seconds out of {2}."
                               "".format(serial, time_elapsed, wait_verify_success))
                time.sleep(wait_interval)
                time_elapsed += wait_interval
        output_message(" Claimed. Continuing..")
    else:
        output_message(" Claimed. Continuing..")

    return


def wait_for_element_state(matching_element, state_list=None, wait_verify_success=DEFAULT_WAIT_MAX_TIME,
                           wait_interval=DEFAULT_WAIT_INTERVAL, destroy_declaim=False):
    """
    Wait for Element to reach a specific state or list of states.
    :param matching_element: Element API response for element to wait for
    :param state_list: Optional - List of state strings, default ['ready', 'bound']
    :param wait_verify_success: Optional - Time to wait for system to reach specific state (in seconds)
    :param wait_interval: Optinal - Interval to check API for updated statuses during wait.
    :return: Element API final response
    """
    if not state_list:
        state_list = ['ready', 'bound']

    # check status
    element = matching_element
    element_id = element.get('id')
    final_element = matching_element

    # ensure element is "state": "ready"
    ready = False
    time_elapsed = 0
    while not ready:
        elem_resp = sdk.get.elements(element_id)
        if not elem_resp.cgx_status:
            throw_error("Could not query element {0}.".format(element_id), elem_resp.cgx_status)
        state = str(elem_resp.cgx_content.get('state', ''))

        # Element is offline. Force back to inventory
        if destroy_declaim is True:
            output_message("Element {0} will be declaimed from the controller. .".format(element_id))

            declaimdata = {"action": "declaim", "parameters": None}
            resp = sdk.post.operations_e(element_id=element_id, data=declaimdata)
            if resp.cgx_status:
                ready = True
                return
            else:
                throw_error("WARN: Element {0} could not be declaimed.".format(element_id))

        if time_elapsed > wait_verify_success:
            # failed waiting.
            throw_error("Element {0} state transition took longer than {1} seconds. Exiting."
                        "".format(element_id, wait_verify_success))

        if state not in state_list:
            # element not ready, wait.
            output_message("  Element {0} not yet in requested state(s): {1} (is {2}). "
                           "Waited so far {3} seconds out of {4}.".format(element_id, ", ".join(state_list), state,
                                                                          time_elapsed, wait_verify_success))
            time.sleep(wait_interval)
            time_elapsed += wait_interval
        else:
            # element is ready.
            ready = True
            # update the element, as the ETAG may have changed.
            final_element = elem_resp.cgx_content

    return final_element


def upgrade_element(matching_element, config_element, wait_upgrade_timeout=DEFAULT_WAIT_MAX_TIME,
                    pause_for_upgrade=True,
                    wait_interval=DEFAULT_WAIT_INTERVAL):
    """
    Upgrade an element to a specific code version (if needed).
    :param matching_element: Element API response to do upgrade/check for.
    :param config_element: Element Configuration object with target version.
    :param wait_upgrade_timeout: Optional - Wait time for upgrade to complete (in seconds)
    :param pause_for_upgrade: Optional - Pause config if upgrade required until complete - Default True
    :param wait_interval: Optional - Interval to check API for updated statuses during wait.
    :return: None
    """
    # check status
    element = matching_element
    element_id = element.get('id')

    # get config info.
    elem_config_version = config_element.get('software_version', '')

    # kick off upgrade
    software_versions_resp = sdk.get.element_images()
    if not software_versions_resp.cgx_status:
        throw_error("unable to get element software images..")
    # find correct image
    images_available = []
    images_id2n = {}
    image_id = None
    for image in software_versions_resp.cgx_content.get('items', []):
        image_version = image.get("version")
        image_lookup_id = image.get('id')
        # build id2n lookup
        images_id2n[image_lookup_id] = image_version
        # now, find the one we are looking for.
        if image_version:
            images_available.append(image_version)
            if image_version.lower() == elem_config_version.lower():
                image_id = image.get('id')

    # did we find image?
    if not image_id:
        throw_error("Unable to find ION Image {0}, found the following: ".format(elem_config_version),
                    images_available)

    # check current image
    software_state_resp = sdk.get.software_status(element_id)
    if not software_state_resp.cgx_status:
        throw_error("Could not query element software status {0}.".format(element_id), software_state_resp)
    backup_active_name = None
    active_image_id = software_state_resp.cgx_content.get('active_image_id')

    if active_image_id is None:
        # attempt to pull active_image_id from status array for newer api.
        prev_image_operations = software_state_resp.cgx_content.get('items')
        if prev_image_operations and isinstance(prev_image_operations, list):
            for prev_image_operation in prev_image_operations:
                operation_active_id = prev_image_operation.get('active_image_id')
                operation_active_name = prev_image_operation.get('active_version')

                if operation_active_name:
                    backup_active_name = operation_active_name

                if operation_active_id:
                    active_image_id = operation_active_id
                    # exit out of for loop
                    break

    # final check
    if active_image_id is None:
        # fail
        active_image_id = ''

    local_debug("ACTIVE_IMAGE_ID: {0}".format(active_image_id), software_state_resp)
    local_debug("REQUESTED IMAGE {0} ID: {1}".format(elem_config_version, image_id))
    local_debug("CURRENT IMAGE IDS AVAILABLE: ", images_id2n)

    if active_image_id == str(image_id):
        # system is already running correct image. Finish.
        output_message(" Element: Code is at correct version {0}.".format(images_id2n.get(active_image_id,
                                                                                          active_image_id)))
        return

    # start upgrade.
    active_name = images_id2n.get(active_image_id, active_image_id)
    if not active_name and backup_active_name:
        # we have a string but unknown image, lets use that.
        active_name = backup_active_name

    output_message(" Element: Changing element from {0} to {1}.".format(active_name if active_name else "Unknown",
                                                                        elem_config_version))
    # Get the object.
    software_state_describe_response = sdk.get.software_state(element_id)

    # Check for API failure
    if not software_state_describe_response.cgx_status:
        throw_error("Unable to get element state: ", software_state_describe_response)

    # Modify the result and put back
    software_state_change = software_state_describe_response.cgx_content
    software_state_change['image_id'] = image_id

    software_state_modify_response = sdk.put.software_state(element_id, software_state_change)

    if not software_state_modify_response.cgx_status:
        throw_error("Upgrade command failed: ", software_state_modify_response)

    updated_software_state_result = software_state_modify_response.cgx_content

    # jd(updated_element_state_result)

    if pause_for_upgrade:
        # wait for upgrade, if set.
        ready = False
        time_elapsed = 0
        while not ready:
            software_state_resp = sdk.get.software_status(element_id)
            if not software_state_resp.cgx_status:
                throw_error("Could not query element software status {0}.".format(element_id), software_state_resp)

            # Get the list of software statuses
            software_status_list = software_state_resp.cgx_content.get('items', [])

            # select the latest software status.
            latest_timestamp = 0
            latest_status = {}
            for current_status in software_status_list:
                current_timestamp = current_status.get("_updated_on_utc", 0)
                if current_timestamp > latest_timestamp:
                    # update most current status
                    latest_timestamp = current_timestamp
                    latest_status = current_status

            active_image_version = str(latest_status.get('active_version'))
            active_image_id = str(latest_status.get('active_image_id'))
            upgrade_image_id = str(latest_status.get('upgrade_image_id', 'Unknown'))

            if time_elapsed > wait_upgrade_timeout:
                # failed waiting.
                throw_error("Element {0} state transition took longer than {1} seconds. Exiting."
                            "".format(element_id, wait_upgrade_timeout))

            if active_image_id != str(image_id):
                # element not ready, wait.
                active_name = images_id2n.get(active_image_id)
                # was this successful? if not, try API reported name, then ID, then say "Unknown".
                if not active_name:
                    active_name = active_image_version if active_image_version else \
                        active_image_id if active_image_id else "Unknown"

                output_message("  Element {0} not yet at requested image: {1} (is {2}). "
                               "Waited so far {3} seconds out of {4}.".format(element_id,
                                                                              images_id2n.get(upgrade_image_id,
                                                                                              upgrade_image_id),
                                                                              active_name if active_name else "Unknown",
                                                                              time_elapsed, wait_upgrade_timeout))
                time.sleep(wait_interval)
                time_elapsed += wait_interval
            else:
                # element is upgraded.
                ready = True

    return


def handle_element_spoke_ha(matching_element, site_id, config_element, interfaces_n2id, spokecluster_n2id):
    """
    Since Spoke HA config is part of the element object, we need to handle it separately.
    :param matching_element: Element ID to work on
    :param site_id: Site ID to work on
    :param config_element: Element config struct
    :param spokecluster_n2id: Spoke Cluster Name -> ID map.
    :return:
    """
    # check status
    element = matching_element
    element_serial = element.get('serial_number')
    element_id = element.get('id')
    element_name_or_id = element.get('name', element_id)
    element_site_id = element.get("site_id")

    # when here, element should always be in assigned state.

    # create template from the matching element.
    elem_template = copy.deepcopy(matching_element)

    # now clean up element template.
    for key in copy.deepcopy(elem_template).keys():
        if key not in element_put_items:
            del elem_template[key]

    # create a copy of element config for cleanup
    config_element_copy = copy.deepcopy(config_element)

    # clean up element config copy
    for key in copy.deepcopy(config_element_copy).keys():
        if key not in element_put_items:
            del config_element_copy[key]

    # replace complex name for spoke_ha_config
    spoke_ha_config = config_element.get('spoke_ha_config')
    if spoke_ha_config:
        # need to look for names
        spoke_ha_config_template = copy.deepcopy(spoke_ha_config)
        name_lookup_in_template(spoke_ha_config_template, 'cluster_id', spokecluster_n2id)
        name_lookup_in_template(spoke_ha_config_template, 'source_interface', interfaces_n2id)
        spoke_ha_config_track = spoke_ha_config.get('track')
        if spoke_ha_config_track:
            spoke_ha_config_track_template = copy.deepcopy(spoke_ha_config_track)
            spoke_ha_config_track_interfaces = spoke_ha_config_track.get("interfaces")
            if spoke_ha_config_track_interfaces:
                spoke_ha_config_track_interfaces_template = []
                for spoke_ha_config_track_interfaces_entry in spoke_ha_config_track_interfaces:
                    spoke_ha_config_track_interfaces_entry_template = \
                        copy.deepcopy(spoke_ha_config_track_interfaces_entry)
                    name_lookup_in_template(spoke_ha_config_track_interfaces_entry_template,
                                            'interface_id', interfaces_n2id)
                    spoke_ha_config_track_interfaces_template.append(spoke_ha_config_track_interfaces_entry_template)
                spoke_ha_config_track_template['interfaces'] = spoke_ha_config_track_interfaces_template
            spoke_ha_config_template['track'] = spoke_ha_config_track_template
        config_element_copy['spoke_ha_config'] = spoke_ha_config_template
    else:
        config_element_copy['spoke_ha_config'] = None

    # Create a copy of the cleaned element template for update check
    element_change_check = copy.deepcopy(elem_template)

    # Update element template with config changes from cleaned copy
    elem_template.update(config_element_copy)

    # Check for changes in cleaned config copy and cleaned template (will finally detect spoke HA changes here):
    if not force_update and elem_template == element_change_check:
        # no change in config, pass.
        output_message("   No Change for Spoke HA in Element {0}.".format(element_name_or_id))
        return

    if debuglevel >= 3:
        local_debug("ELEMENT SPOKEHA DIFF: {0}".format(find_diff(element_change_check, elem_template)))

    output_message("   Updating Spoke HA for Element {0}.".format(element_name_or_id))

    # clean up element template.
    for key in copy.deepcopy(elem_template).keys():
        if key not in element_put_items:
            del elem_template[key]

    # Add missing elem attributes
    elem_template['sw_obj'] = None

    local_debug("ELEM_SPOKEHA_TEMPLATE_FINAL: " + str(json.dumps(elem_template, indent=4)))

    elem_update_resp = sdk.put.elements(element_id, elem_template)

    if not elem_update_resp.cgx_status:
        throw_error("Element Spoke HA {0} Update failed: ".format(element_id), elem_update_resp)

    return


def assign_modify_element(matching_element, site_id, config_element):
    """
    Assign or Modify element object
    :param matching_element: Element API response
    :param site_id: Site ID where element is or will be assigned.
    :param config_element: Element Configuration object
    :return: None
    """
    # check status
    element = matching_element
    element_serial = element.get('serial_number')
    element_id = element.get('id')
    element_site_id = element.get("site_id")

    # 5.0.1 element_site_id is set to 1 instead of None when unassigned.
    if element_site_id and element_site_id not in ['1', 1]:
        # element is already assigned.

        if element_site_id == site_id:
            # Element needs Update check

            # check status
            element_id = element.get('id')

            # create template from the matching element.
            elem_template = copy.deepcopy(matching_element)

            # now clean up element template.
            for key in copy.deepcopy(elem_template).keys():
                if key not in element_put_items:
                    del elem_template[key]

            # create a copy of element config for cleanup
            config_element_copy = copy.deepcopy(config_element)

            # clean up element config copy
            for key in copy.deepcopy(config_element_copy).keys():
                if key not in element_put_items:
                    del config_element_copy[key]

            # Create a copy of the cleaned element template for update check
            element_change_check = copy.deepcopy(elem_template)

            # We don't want to do any spoke_ha_config changes here. Copy the current spoke_ha config over the YAML
            # config. We'll pick up the new config AFTER enumerating the interfaces.
            config_element_copy['spoke_ha_config'] = elem_template.get('spoke_ha_config', None)

            # Update element template with config changes from cleaned copy
            elem_template.update(config_element_copy)

            # Check for changes in cleaned config copy and cleaned template (will not detect spoke HA changes here):
            if not force_update and elem_template == element_change_check:
                # no change in config, pass.
                element_name = matching_element.get('name')
                output_message("  No Change for Element {0}.".format(element_name))
                return

            if debuglevel >= 3:
                local_debug("ELEMENT DIFF: {0}".format(find_diff(element_change_check, elem_template)))

            output_message("  Updating Element {0}.".format(element_id))

            # clean up element template.
            for key in copy.deepcopy(elem_template).keys():
                if key not in element_put_items:
                    del elem_template[key]

            # Add missing elem attributes
            elem_template['sw_obj'] = None

            local_debug("ELEM_TEMPLATE_FINAL: " + str(json.dumps(elem_template, indent=4)))

            elem_update_resp = sdk.put.elements(element_id, elem_template)

            if not elem_update_resp.cgx_status:
                throw_error("Element {0} Update failed: ".format(element_id), elem_update_resp)

            return

        else:
            # Element is assigned to another site, fail.
            # build sites ID to name map from cache.
            sites_id2n = build_lookup_dict(sites_cache, key_val='id', value_val='name')
            throw_error("Element {0}({1}) is already assigned to site {2}. It needs to be in 'Claimed' state before"
                        "assigning to a new site.".format(element_id,
                                                          element_serial,
                                                          sites_id2n.get(element_site_id, element_site_id)))

    else:
        # Element needs assigned.
        output_message("  Assigning Element {0}.".format(element_id))
        # check status
        element_id = element.get('id')

        # create template from the matching element.
        elem_template = copy.deepcopy(matching_element)

        # update from the config
        elem_template.update(config_element)

        # clean up element template.
        for key in copy.deepcopy(elem_template).keys():
            if key not in element_put_items:
                del elem_template[key]

        # Add missing elem attributes
        elem_template['sw_obj'] = None
        elem_template['site_id'] = site_id

        # Ensure spoke HA config is blank for Element assignment:
        elem_template['spoke_ha_config'] = None

        local_debug("ELEM_TEMPLATE_FINAL: " + str(json.dumps(elem_template, indent=4)))

        elem_update_resp = sdk.put.elements(element_id, elem_template)

        if not elem_update_resp.cgx_status:
            throw_error("Element {0} Assign failed: ".format(element_id), elem_update_resp)

    return


def unbind_elements(element_id_list, site_id):
    """
    Unbind element(s) from a site
    :param element_id_list: List of element IDs to unbind.
    :param site_id: Site ID to unbind element from.
    :return:
    """
    # get the element records from cache that match the element IDs we want to unbind from the site.
    elem_list = [element for element in elements_cache if element.get('id') in element_id_list]

    for element_item in elem_list:
        element_item_id = element_item.get('id')
        element_item_name = element_item.get('name')
        element_item_site_id = element_item.get('site_id')

        # select this element to destroy, but double verify it is assigned to the site.
        if element_item_site_id == site_id:
            output_message("Un-assigning element {0}({1}) bound to {2}.".format(element_item_name, element_item_id,
                                                                                site_id))

            # Remove LAN/WAN labels from intefaces.
            intf_resp = sdk.get.interfaces(site_id, element_item_id)

            if not intf_resp.cgx_status:
                throw_error("Could not get list of element {0} interfaces: ".format(element_item_name),
                            intf_resp)

            intf_list = intf_resp.cgx_content.get('items', [])

            bypass_member_list = []

            # look for interfaces that are members of a bypass list.
            for interface in intf_list:
                bypass_pair = interface.get('bypass_pair', {})
                if bypass_pair and isinstance(bypass_pair, dict):
                    wan = bypass_pair.get('wan')
                    if wan:
                        bypass_member_list.append(wan)
                    lan = bypass_pair.get('lan')
                    if lan:
                        bypass_member_list.append(lan)

            # iterate the interface list, removing all lan networks/ wan interfaces.
            for interface in intf_list:

                intf_name = interface.get('name')
                intf_id = interface.get('id')

                if intf_name not in skip_interface_list and intf_id not in bypass_member_list:
                    changed = False

                    intf_template = copy.deepcopy(interface)

                    if "site_wan_interface_ids" in interface:
                        changed = True
                        intf_template["site_wan_interface_ids"] = None

                    if "attached_lan_networks" in interface:
                        changed = True
                        intf_template["attached_lan_networks"] = None

                    if changed and intf_name and intf_id:
                        # reconfigure the interface.
                        output_message(" Removing LAN Networks/WAN Interfaces from {0}.".format(intf_name))
                        reconf_resp = sdk.put.interfaces(site_id, element_item_id, intf_id, intf_template)

                        if not reconf_resp.cgx_status:
                            throw_error("Could not strip config from {0}: ".format(intf_name),
                                        reconf_resp.cgx_content)

            # Remove static routes from device.
            static_routes_resp = sdk.get.staticroutes(site_id, element_item_id)

            if not static_routes_resp.cgx_status:
                throw_error("Could not get list of element {0} static routes: ".format(element_item_name),
                            static_routes_resp)

            static_routes_list = static_routes_resp.cgx_content.get('items', [])

            # Get a list of static routes bound to this element
            delete_static_route_id_list = [x['id'] for x in static_routes_list if x.get('id')]

            # Delete the routes
            delete_staticroutes(delete_static_route_id_list, site_id, element_item_id)

            # prepare to unbind element.
            elem_template = copy.deepcopy(element_item)

            # clean up element template.
            for key in copy.deepcopy(elem_template).keys():
                if key not in element_put_items:
                    del elem_template[key]

            # Add missing elem attributes
            elem_template['sw_obj'] = None
            elem_template['site_id'] = 1

            # Wipe them out. All of them..
            elem_resp = sdk.put.elements(element_item_id, elem_template)
            if not elem_resp.cgx_status:
                throw_error("Could not unbind element {0}: ".format(element_item_name), elem_resp.cgx_content)

        else:
            throw_warning("Element {0}({1}) not bound to {2}.".format(element_item_name, element_item_id,
                                                                      site_id))

    # return the unbound element object entries.
    return elem_list


def create_site(config_site):
    """
    Create a new site
    :param config_site: Site configuration Dict
    :return: New site ID
    """
    global sites_cache
    global sites_n2id

    # make a copy of site to modify
    site_template = copy.deepcopy(config_site)
    # remove non-site items
    site_template = fuzzy_pop(site_template, 'waninterfaces')
    site_template = fuzzy_pop(site_template, 'lannetworks')
    site_template = fuzzy_pop(site_template, 'elements')
    site_template = fuzzy_pop(site_template, 'dhcpservers')
    site_template = fuzzy_pop(site_template, 'hubclusters')
    site_template = fuzzy_pop(site_template, 'site_extensions')
    site_template = fuzzy_pop(site_template, 'site_security_zones')
    site_template = fuzzy_pop(site_template, 'spokeclusters')

    # perform name -> ID lookups
    name_lookup_in_template(site_template, 'policy_set_id', policysets_n2id)
    name_lookup_in_template(site_template, 'security_policyset_id', security_policysets_n2id)
    name_lookup_in_template(site_template, 'network_policysetstack_id', network_policysetstack_n2id)
    name_lookup_in_template(site_template, 'priority_policysetstack_id', priority_policysetstack_n2id)
    name_lookup_in_template(site_template, 'service_binding', servicebindingmaps_n2id)

    local_debug("SITE TEMPLATE: " + str(json.dumps(site_template, indent=4)))

    # create site
    site_resp = sdk.post.sites(site_template)

    if not site_resp.cgx_status:
        throw_error("Site creation failed: ", site_resp)

    site_name = site_resp.cgx_content.get('name')
    site_id = site_resp.cgx_content.get('id')

    if not site_name or not site_id:
        throw_error("Unable to determine site attributes (Name: {0}, ID {1})..".format(site_name, site_id))

    output_message("Created Site {0}.".format(site_name))
    # note, site always created disabled, need to set final state after config.

    # update caches
    sites_n2id[site_name] = site_id

    return site_id


def modify_site(config_site, site_id):
    """
    Modify an existing Site
    :param config_site: Site config Dict
    :param site_id: Existing Site ID
    :return: Returned Site ID
    """
    global sites_cache
    global sites_n2id

    site_config = {}
    # make a copy of site to modify
    site_template = copy.deepcopy(config_site)
    # remove non-site items
    site_template = fuzzy_pop(site_template, 'waninterfaces')
    site_template = fuzzy_pop(site_template, 'lannetworks')
    site_template = fuzzy_pop(site_template, 'elements')
    site_template = fuzzy_pop(site_template, 'dhcpservers')
    site_template = fuzzy_pop(site_template, 'hubclusters')
    site_template = fuzzy_pop(site_template, 'site_extensions')
    site_template = fuzzy_pop(site_template, 'site_security_zones')
    site_template = fuzzy_pop(site_template, 'spokeclusters')

    # perform name -> ID lookups
    name_lookup_in_template(site_template, 'policy_set_id', policysets_n2id)
    name_lookup_in_template(site_template, 'security_policyset_id', security_policysets_n2id)
    name_lookup_in_template(site_template, 'network_policysetstack_id', network_policysetstack_n2id)
    name_lookup_in_template(site_template, 'priority_policysetstack_id', priority_policysetstack_n2id)
    name_lookup_in_template(site_template, 'service_binding', servicebindingmaps_n2id)

    local_debug("SITE TEMPLATE: " + str(json.dumps(site_template, indent=4)))

    # get current site
    site_resp = sdk.get.sites(site_id)
    if site_resp.cgx_status:
        site_config = site_resp.cgx_content
    else:
        throw_error("Unable to retrieve site: ", site_resp)

    # extract prev_revision
    prev_revision = site_config.get("_etag")

    # Check for changes:
    site_change_check = copy.deepcopy(site_config)
    site_config.update(site_template)

    if not force_update and site_config == site_change_check:
        # no change in config, pass.
        site_id = site_change_check.get('id')
        site_name = site_change_check.get('name')
        output_message("No Change for Site {0}.".format(site_name))
        return site_id

    if debuglevel >= 3:
        local_debug("SITE DIFF: {0}".format(find_diff(site_change_check, site_config)))

    # Update Site.
    site_resp2 = sdk.put.sites(site_id, site_config)

    if not site_resp2.cgx_status:
        throw_error("Site update failed: ", site_resp2)

    site_name = site_resp2.cgx_content.get('name')
    site_id = site_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = site_resp2.cgx_content.get("_etag")

    if not site_name or not site_id:
        throw_error("Unable to determine site attributes (Name: {0}, ID {1})..".format(site_name, site_id))

    output_message("Updated Site {0} (Etag {1} -> {2}).".format(site_name, prev_revision, current_revision))
    # note, site always created disabled, need to set final state after config.

    # update caches
    sites_n2id[site_name] = site_id

    return site_id


def set_site_state(config_site, site_id):
    """
    Modify Site state specifically.
    :param config_site: Site configuration Dict
    :param site_id: Existing site ID
    :return: Returned Site ID
    """
    site_state = config_site.get('admin_state')
    site_name = config_site.get('name', site_id)

    if not site_state:
        site_state = 'disabled'

    # get site
    site_resp = sdk.get.sites(site_id)

    if not site_resp.cgx_status:
        throw_error("Get of site {0} failed: ".format(site_id), site_resp.cgx_content)

    # check state
    cur_state = site_resp.cgx_content.get('admin_state')
    if not force_update and cur_state is not None and cur_state == site_state:
        # already this state.
        output_message("No Change for Site {0} state ({1}).".format(site_name, site_state))
        return

    site_resp.cgx_content['admin_state'] = site_state

    # put it back
    site_modify_resp = sdk.put.sites(site_id, site_resp.cgx_content)
    if not site_modify_resp.cgx_status:
        throw_error("Set of site {0} status failed: ".format(site_id), site_modify_resp.cgx_content)

    output_message("Updated Site {0} to state {1}.".format(site_name, site_state))

    return


def create_waninterface(config_waninterface, waninterfaces_n2id, site_id):
    """
    Create a WAN Interface
    :param config_waninterface: WAN Interface config dict
    :param waninterfaces_n2id: WAN Interface Name to ID dict
    :param site_id: Site ID to use
    :return: New WAN Interface ID
    """
    # make a copy of waninterface to modify
    waninterface_template = copy.deepcopy(config_waninterface)

    # perform name -> ID lookups
    name_lookup_in_template(waninterface_template, 'network_id', wannetworks_n2id)
    name_lookup_in_template(waninterface_template, 'label_id', waninterfacelabels_n2id)

    local_debug("WANINTERFACE TEMPLATE: " + str(json.dumps(waninterface_template, indent=4)))

    # create waninterface
    waninterface_resp = sdk.post.waninterfaces(site_id, waninterface_template)

    if not waninterface_resp.cgx_status:
        throw_error("Waninterface creation failed: ", waninterface_resp)

    waninterface_name = waninterface_resp.cgx_content.get('name')
    waninterface_id = waninterface_resp.cgx_content.get('id')

    if not waninterface_name or not waninterface_id:
        throw_error("Unable to determine waninterface attributes (Name: {0}, ID {1})..".format(waninterface_name,
                                                                                               waninterface_id))

    output_message(" Created waninterface {0}.".format(waninterface_name))

    # update caches
    waninterfaces_n2id[waninterface_name] = waninterface_id

    return waninterface_id


def modify_waninterface(config_waninterface, waninterface_id, waninterfaces_n2id, site_id):
    """
    Modify Existing WAN Interface
    :param config_waninterface: WAN Interface config dict
    :param waninterface_id: Existing WAN Interface ID
    :param waninterfaces_n2id: WAN Interface Name to ID dict
    :param site_id: Site ID to use
    :return: Returned WAN Interface ID
    """
    waninterface_config = {}
    # make a copy of waninterface to modify
    waninterface_template = copy.deepcopy(config_waninterface)

    # perform name -> ID lookups
    name_lookup_in_template(waninterface_template, 'network_id', wannetworks_n2id)
    name_lookup_in_template(waninterface_template, 'label_id', waninterfacelabels_n2id)

    local_debug("WANINTERFACE TEMPLATE: " + str(json.dumps(waninterface_template, indent=4)))

    # get current waninterface
    waninterface_resp = sdk.get.waninterfaces(site_id, waninterface_id)
    if waninterface_resp.cgx_status:
        waninterface_config = waninterface_resp.cgx_content
    else:
        throw_error("Unable to retrieve waninterface: ", waninterface_resp)

    # extract prev_revision
    prev_revision = waninterface_config.get("_etag")

    # Check for changes:
    waninterface_change_check = copy.deepcopy(waninterface_config)
    waninterface_config.update(waninterface_template)
    if not force_update and waninterface_config == waninterface_change_check:
        # no change in config, pass.
        waninterface_id = waninterface_change_check.get('id')
        waninterface_name = waninterface_change_check.get('name')
        output_message(" No Change for Waninterface {0}.".format(waninterface_name))
        return waninterface_id

    if debuglevel >= 3:
        local_debug("WANINTERFACE DIFF: {0}".format(find_diff(waninterface_change_check, waninterface_config)))

    # check for network_id changes. These are not supported in current release.
    api_network_id = waninterface_change_check.get("network_id")
    config_network_id = waninterface_config.get("network_id")

    if api_network_id != config_network_id:
        api_name = waninterface_change_check.get('name')
        config_name = waninterface_config.get('name')

        if api_name != config_name:
            error_text = "WAN Interface {0}->{1}(ID: {2}) config has changed 'network_id'. This is not supported. " \
                         "To change the network_id, please remove the WAN Interface and re-create it with the new" \
                         "network_id in a subsequent run.".format(api_name, config_name, waninterface_id)
        else:
            error_text = "WAN Interface {0}(ID: {1}) config has changed 'network_id'. This is not supported. " \
                         "To change the network_id, please remove the WAN Interface and re-create it with the new " \
                         "network_id in a subsequent run.".format(api_name, waninterface_id)
        error_dict = {
            "FROM CONFIG": waninterface_config,
            "ON CONTROLLER": waninterface_change_check
        }
        throw_error(error_text, error_dict)

    # Update Waninterface.
    waninterface_resp2 = sdk.put.waninterfaces(site_id, waninterface_id, waninterface_config)

    if not waninterface_resp2.cgx_status:
        throw_error("Waninterface update failed: ", waninterface_resp2)

    waninterface_name = waninterface_resp2.cgx_content.get('name')
    waninterface_id = waninterface_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = waninterface_resp2.cgx_content.get("_etag")

    if not waninterface_name or not waninterface_id:
        throw_error("Unable to determine waninterface attributes (Name: {0}, ID {1})..".format(waninterface_name,
                                                                                               waninterface_id))

    output_message(" Updated Waninterface {0} (Etag {1} -> {2}).".format(waninterface_name, prev_revision,
                                                                         current_revision))

    # update caches
    waninterfaces_n2id[waninterface_name] = waninterface_id

    return waninterface_id


def delete_waninterfaces(leftover_waninterfaces, site_id, id2n=None):
    """
    Delete WAN Interfaces
    :param leftover_waninterfaces: List of WAN Interface IDs to delete
    :param site_id: Site ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for waninterface_id in leftover_waninterfaces:
        # delete all leftover waninterfaces.

        output_message(" Deleting Unconfigured Waninterface {0}.".format(id2n.get(waninterface_id, waninterface_id)))
        waninterface_del_resp = sdk.delete.waninterfaces(site_id, waninterface_id)
        if not waninterface_del_resp.cgx_status:
            throw_error("Could not delete Waninterface {0}: ".format(id2n.get(waninterface_id, waninterface_id)),
                        waninterface_del_resp)
    return


def create_lannetwork(config_lannetwork, lannetworks_n2id, site_id):
    """
    Create LAN Network
    :param config_lannetwork: LAN Network config dict
    :param lannetworks_n2id: LAN Network ID to Name dict
    :param site_id: Site ID to use
    :return: New LAN Network ID
    """
    # make a copy of lannetwork to modify
    lannetwork_template = copy.deepcopy(config_lannetwork)

    # perform name -> ID lookups
    name_lookup_in_template(lannetwork_template, 'security_policy_set', security_policysets_n2id)
    name_lookup_in_template(lannetwork_template, 'network_context_id', networkcontexts_n2id)

    local_debug("LANNETWORK TEMPLATE: " + str(json.dumps(lannetwork_template, indent=4)))

    # create lannetwork
    lannetwork_resp = sdk.post.lannetworks(site_id, lannetwork_template)

    if not lannetwork_resp.cgx_status:
        throw_error("Lannetwork creation failed: ", lannetwork_resp)

    lannetwork_name = lannetwork_resp.cgx_content.get('name')
    lannetwork_id = lannetwork_resp.cgx_content.get('id')

    if not lannetwork_name or not lannetwork_id:
        throw_error("Unable to determine lannetwork attributes (Name: {0}, ID {1})..".format(lannetwork_name,
                                                                                             lannetwork_id))

    output_message(" Created lannetwork {0}.".format(lannetwork_name))

    # update caches
    lannetworks_n2id[lannetwork_name] = lannetwork_id

    return lannetwork_id


def modify_lannetwork(config_lannetwork, lannetwork_id, lannetworks_n2id, site_id):
    """
    Modify an existing LAN Network
    :param config_lannetwork: LAN Network config dict
    :param lannetwork_id: Existing LAN Network ID
    :param lannetworks_n2id: LAN Network ID to Name dict
    :param site_id: Site ID to use
    :return: Returned LAN Network ID
    """
    lannetwork_config = {}
    # make a copy of lannetwork to modify
    lannetwork_template = copy.deepcopy(config_lannetwork)

    # perform name -> ID lookups
    name_lookup_in_template(lannetwork_template, 'security_policy_set', security_policysets_n2id)
    name_lookup_in_template(lannetwork_template, 'network_context_id', networkcontexts_n2id)

    local_debug("LANNETWORK TEMPLATE: " + str(json.dumps(lannetwork_template, indent=4)))

    # get current lannetwork
    lannetwork_resp = sdk.get.lannetworks(site_id, lannetwork_id)
    if lannetwork_resp.cgx_status:
        lannetwork_config = lannetwork_resp.cgx_content
    else:
        throw_error("Unable to retrieve lannetwork: ", lannetwork_resp)

    # extract prev_revision
    prev_revision = lannetwork_config.get("_etag")

    # Check for changes:
    lannetwork_change_check = copy.deepcopy(lannetwork_config)
    lannetwork_config.update(lannetwork_template)
    if not force_update and lannetwork_config == lannetwork_change_check:
        # no change in config, pass.
        lannetwork_id = lannetwork_change_check.get('id')
        lannetwork_name = lannetwork_change_check.get('name')
        output_message(" No Change for Lannetwork {0}.".format(lannetwork_name))
        return lannetwork_id

    if debuglevel >= 3:
        local_debug("LANNETWORK DIFF: {0}".format(find_diff(lannetwork_change_check, lannetwork_config)))

    # Update Lannetwork.
    lannetwork_resp2 = sdk.put.lannetworks(site_id, lannetwork_id, lannetwork_config)

    if not lannetwork_resp2.cgx_status:
        throw_error("Lannetwork update failed: ", lannetwork_resp2)

    lannetwork_name = lannetwork_resp2.cgx_content.get('name')
    lannetwork_id = lannetwork_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = lannetwork_resp2.cgx_content.get("_etag")

    if not lannetwork_name or not lannetwork_id:
        throw_error("Unable to determine lannetwork attributes (Name: {0}, ID {1})..".format(lannetwork_name,
                                                                                             lannetwork_id))

    output_message(" Updated Lannetwork {0} (Etag {1} -> {2}).".format(lannetwork_name, prev_revision,
                                                                       current_revision))

    # update caches
    lannetworks_n2id[lannetwork_name] = lannetwork_id

    return lannetwork_id


def delete_lannetworks(leftover_lannetworks, site_id, id2n=None):
    """
    Delete a list of LAN Networks
    :param leftover_lannetworks: list of LAN Network IDs
    :param site_id: Site ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for lannetwork_id in leftover_lannetworks:
        # delete all leftover lannetworks.

        output_message(" Deleting Unconfigured Lannetwork {0}.".format(id2n.get(lannetwork_id, lannetwork_id)))
        lannetwork_del_resp = sdk.delete.lannetworks(site_id, lannetwork_id)
        if not lannetwork_del_resp.cgx_status:
            throw_error("Could not delete Lannetwork {0}: ".format(id2n.get(lannetwork_id, lannetwork_id)),
                        lannetwork_del_resp)
    return


def create_dhcpserver(config_dhcpserver, site_id):
    """
    Create a new DHCP Server
    :param config_dhcpserver: DHCP Server config dict
    :param site_id: Site ID to use
    :return: New DHCP Server ID
    """
    # make a copy of dhcpserver to modify
    dhcpserver_template = copy.deepcopy(config_dhcpserver)

    # replace flat names
    name_lookup_in_template(dhcpserver_template, 'network_context_id', networkcontexts_n2id)

    local_debug("DHCPSERVER TEMPLATE: " + str(json.dumps(dhcpserver_template, indent=4)))

    # create dhcpserver
    dhcpserver_resp = sdk.post.dhcpservers(site_id, dhcpserver_template)

    if not dhcpserver_resp.cgx_status:
        throw_error("Dhcpserver creation failed: ", dhcpserver_resp)

    dhcpserver_id = dhcpserver_resp.cgx_content.get('id')
    dhcpserver_subnet = dhcpserver_resp.cgx_content.get('subnet', dhcpserver_id)

    if not dhcpserver_id:
        throw_error("Unable to determine dhcpserver attributes (ID {0})..".format(dhcpserver_id))

    output_message(" Created dhcpserver for {0}.".format(dhcpserver_subnet))

    return dhcpserver_id


def modify_dhcpserver(config_dhcpserver, dhcpserver_id, site_id):
    """
    Modify an existing DHCP Server
    :param config_dhcpserver: DHCP Server config dict
    :param dhcpserver_id: Existing DHCP Server ID
    :param site_id: Site ID to use
    :return: Returned DHCP Server ID
    """
    dhcpserver_config = {}
    # make a copy of dhcpserver to modify
    dhcpserver_template = copy.deepcopy(config_dhcpserver)

    # replace flat names
    name_lookup_in_template(dhcpserver_template, 'network_context_id', networkcontexts_n2id)

    local_debug("DHCPSERVER TEMPLATE: " + str(json.dumps(dhcpserver_template, indent=4)))

    # get current dhcpserver
    dhcpserver_resp = sdk.get.dhcpservers(site_id, dhcpserver_id)
    if dhcpserver_resp.cgx_status:
        dhcpserver_config = dhcpserver_resp.cgx_content
    else:
        throw_error("Unable to retrieve DHCPServer: ", dhcpserver_resp)

    # extract prev_revision
    prev_revision = dhcpserver_config.get("_etag")

    # Check for changes:
    dhcpserver_change_check = copy.deepcopy(dhcpserver_config)
    dhcpserver_config.update(dhcpserver_template)
    if not force_update and dhcpserver_config == dhcpserver_change_check:
        # no change in config, pass.
        dhcpserver_id = dhcpserver_change_check.get('id')
        dhcpserver_subnet = dhcpserver_change_check.get('subnet')
        output_message(" No Change for Dhcpserver for {0}.".format(dhcpserver_subnet))
        return dhcpserver_id

    if debuglevel >= 3:
        local_debug("DHCPSERVER DIFF: {0}".format(find_diff(dhcpserver_change_check, dhcpserver_config)))

    # Update Dhcpserver.
    dhcpserver_resp2 = sdk.put.dhcpservers(site_id, dhcpserver_id, dhcpserver_config)

    if not dhcpserver_resp2.cgx_status:
        throw_error("Dhcpserver update failed: ", dhcpserver_resp2)

    dhcpserver_id = dhcpserver_resp.cgx_content.get('id')
    dhcpserver_subnet = dhcpserver_resp.cgx_content.get('subnet', dhcpserver_id)

    # extract current_revision
    current_revision = dhcpserver_resp2.cgx_content.get("_etag")

    if not dhcpserver_id:
        throw_error("Unable to determine dhcpserver attributes (ID {0})..".format(dhcpserver_id))

    output_message(" Updated Dhcpserver for {0} (Etag {1} -> {2}).".format(dhcpserver_subnet, prev_revision,
                                                                           current_revision))

    return dhcpserver_id


def delete_dhcpservers(leftover_dhcpservers, site_id, id2n=None):
    """
    Delete a list of DHCP servers
    :param leftover_dhcpservers: List of DHCP Server IDs to delete
    :param site_id: Site ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for dhcpserver_id in leftover_dhcpservers:
        # delete all leftover dhcpservers.

        output_message("Deleting Unconfigured Dhcpserver for {0}.".format(id2n.get(dhcpserver_id, dhcpserver_id)))
        dhcpserver_del_resp = sdk.delete.dhcpservers(site_id, dhcpserver_id)
        if not dhcpserver_del_resp.cgx_status:
            throw_error("Could not delete Dhcpserver {0}: ".format(id2n.get(dhcpserver_id, dhcpserver_id)),
                        dhcpserver_del_resp)
    return


def create_site_extension(config_site_extension, site_extensions_n2id, waninterfaces_n2id, lannetworks_n2id, site_id):
    """
    Create a new Site Extension
    :param config_site_extension: Site Extension config dict
    :param site_extensions_n2id: Site Extension Name to ID dict
    :param waninterfaces_n2id: WAN Interface Name to ID dict
    :param lannetworks_n2id: LAN Networks Name to ID dict
    :param site_id: Site ID to use
    :return: Created Site Extension ID
    """
    # make a copy of site_extension to modify
    site_extension_template = copy.deepcopy(config_site_extension)

    # Entity ID can be a multitude of things. Try them all.
    name_lookup_in_template(site_extension_template, 'entity_id', waninterfaces_n2id)
    name_lookup_in_template(site_extension_template, 'entity_id', lannetworks_n2id)
    # look up appdefs last, as appdef id 0 = unknown, and may match other 0's
    name_lookup_in_template(site_extension_template, 'entity_id', appdefs_n2id)

    local_debug("SITE_EXTENSION TEMPLATE: " + str(json.dumps(site_extension_template, indent=4)))

    # create site_extension
    site_extension_resp = sdk.post.site_extensions(site_id, site_extension_template)

    if not site_extension_resp.cgx_status:
        throw_error("Site_extension creation failed: ", site_extension_resp)

    site_extension_name = site_extension_resp.cgx_content.get('name')
    site_extension_id = site_extension_resp.cgx_content.get('id')

    if not site_extension_name or not site_extension_id:
        throw_error("Unable to determine site_extension attributes (Name: {0}, ID {1}).."
                    "".format(site_extension_name, site_extension_id))

    output_message(" Created site extension {0}.".format(site_extension_name))

    # update caches
    site_extensions_n2id[site_extension_name] = site_extension_id

    return site_extension_id


def modify_site_extension(config_site_extension, site_extension_id, site_extensions_n2id, waninterfaces_n2id,
                          lannetworks_n2id, site_id):
    """
    Modify existing Site Extension
    :param config_site_extension: Site Extension config dict
    :param site_extension_id: Existing Site Extension ID
    :param site_extensions_n2id: Site Extension Name to ID dict
    :param waninterfaces_n2id: WAN Interface Name to ID dict
    :param lannetworks_n2id: LAN Networks Name to ID dict
    :param site_id: Site ID to use
    :return: Returned Site Extension ID
    """
    site_extension_config = {}
    # make a copy of site_extension to modify
    site_extension_template = copy.deepcopy(config_site_extension)

    # Entity ID can be a multitude of things. Try them all.
    name_lookup_in_template(site_extension_template, 'entity_id', waninterfaces_n2id)
    name_lookup_in_template(site_extension_template, 'entity_id', lannetworks_n2id)
    # look up appdefs last, as appdef id 0 = unknown, and may match other 0's
    name_lookup_in_template(site_extension_template, 'entity_id', appdefs_n2id)

    local_debug("SITE_EXTENSION TEMPLATE: " + str(json.dumps(site_extension_template, indent=4)))

    # get current site_extension
    site_extension_resp = sdk.get.site_extensions(site_id, site_extension_id)
    if site_extension_resp.cgx_status:
        site_extension_config = site_extension_resp.cgx_content
    else:
        throw_error("Unable to retrieve site_extension: ", site_extension_resp)

    # extract prev_revision
    prev_revision = site_extension_config.get("_etag")

    # Check for changes:
    site_extension_change_check = copy.deepcopy(site_extension_config)
    site_extension_config.update(site_extension_template)
    if not force_update and site_extension_config == site_extension_change_check:
        # no change in config, pass.
        site_extension_id = site_extension_change_check.get('id')
        site_extension_name = site_extension_change_check.get('name')
        output_message(" No Change for Site_extension {0}.".format(site_extension_name))
        return site_extension_id

    if debuglevel >= 3:
        local_debug("SITE_EXTENSION DIFF: {0}".format(find_diff(site_extension_change_check, site_extension_config)))

    # Update Site_extension.
    site_extension_resp2 = sdk.put.site_extensions(site_id, site_extension_id, site_extension_config)

    if not site_extension_resp2.cgx_status:
        throw_error("Site_extension update failed: ", site_extension_resp2)

    site_extension_name = site_extension_resp2.cgx_content.get('name')
    site_extension_id = site_extension_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = site_extension_resp2.cgx_content.get("_etag")

    if not site_extension_name or not site_extension_id:
        throw_error("Unable to determine site_extension attributes (Name: {0}, ID {1}).."
                    "".format(site_extension_name, site_extension_id))

    output_message(" Updated Site extension {0} (Etag {1} -> {2}).".format(site_extension_name, prev_revision,
                                                                           current_revision))

    # update caches
    site_extensions_n2id[site_extension_name] = site_extension_id

    return site_extension_id


def delete_site_extensions(leftover_site_extensions, site_id, id2n=None):
    """
    Delete a list of Site Extensions
    :param leftover_site_extensions: List of Site Extension IDs
    :param site_id: Site ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for site_extension_id in leftover_site_extensions:
        # delete all leftover site_extensions.

        output_message(" Deleting Unconfigured Site_extension {0}.".format(id2n.get(site_extension_id,
                                                                           site_extension_id)))
        site_extension_del_resp = sdk.delete.site_extensions(site_id, site_extension_id)
        if not site_extension_del_resp.cgx_status:
            throw_error("Could not delete Site_extension {0}: ".format(id2n.get(site_extension_id,
                                                                                site_extension_id)),
                        site_extension_del_resp)
    return


def create_site_securityzone(config_site_securityzone, waninterface_n2id, lannetworks_n2id, site_id):
    """
    Create a Site Security Zone Mapping
    :param config_site_securityzone: Site Securityzone config dict
    :param waninterface_n2id: Site WAN InterfaceName to ID map (site specific)
    :param lannetworks_n2id: LAN Networks Name to ID map (site specific)
    :param site_id: Site ID to use
    :return: Site Securityzone
    """
    # make a copy of site_securityzone to modify
    site_securityzone_template = copy.deepcopy(config_site_securityzone)

    # perform name -> ID lookups
    name_lookup_in_template(site_securityzone_template, 'zone_id', securityzones_n2id)

    # replace complex names
    ssz_networks = site_securityzone_template.get('networks', None)
    if ssz_networks and isinstance(ssz_networks, list):
        ssz_networks_template = []
        for ssz_network in ssz_networks:
            ssz_network_template = copy.deepcopy(ssz_network)
            ssz_network_type = ssz_network.get('network_type')
            if ssz_network_type and ssz_network_type.lower() in ['wan_network', 'wan_overlay', 'lan_network']:
                if ssz_network_type.lower() == 'wan_network':
                    name_lookup_in_template(ssz_network_template, 'network_id', waninterface_n2id)
                elif ssz_network_type.lower() == 'wan_overlay':
                    name_lookup_in_template(ssz_network_template, 'network_id', wanoverlays_n2id)
                elif ssz_network_type.lower() == 'lan_network':
                    name_lookup_in_template(ssz_network_template, 'network_id', lannetworks_n2id)

            ssz_networks_template.append(ssz_network_template)
        site_securityzone_template['networks'] = ssz_networks_template

    local_debug("SITE_SECURITYZONE TEMPLATE: " + str(json.dumps(site_securityzone_template, indent=4)))

    # create site_securityzone
    site_securityzone_resp = sdk.post.sitesecurityzones(site_id, site_securityzone_template)

    if not site_securityzone_resp.cgx_status:
        throw_error("Site Securityzone creation failed: ", site_securityzone_resp)

    site_securityzone_id = site_securityzone_resp.cgx_content.get('id')
    site_securityzone_zone_id = site_securityzone_resp.cgx_content.get('zone_id')

    if not site_securityzone_id or not site_securityzone_zone_id:
        throw_error("Unable to determine site_securityzone attributes (ID {0}, Zone ID {1}).."
                    "".format(site_securityzone_id, site_securityzone_zone_id))

    # Try to get zone name this is for.
    ssz_zone_name = securityzones_id2n.get(site_securityzone_zone_id, site_securityzone_zone_id)

    output_message(" Created Site Securityzone Mapping for Zone '{0}'.".format(ssz_zone_name))

    return site_securityzone_id


def modify_site_securityzone(config_site_securityzone, site_securityzone_id, waninterface_n2id, lannetworks_n2id,
                             site_id):
    """
    Modify Existing Site Security Zone Mapping
    :param config_site_securityzone: Site Securityzone config dict
    :param site_securityzone_id: Existing Site Securityzone ID
    :param waninterface_n2id: Site WAN InterfaceName to ID map (site specific)
    :param lannetworks_n2id: LAN Networks Name to ID map (site specific)
    :param site_id: Site ID to use
    :return: Returned Site Securityzone ID
    """
    site_securityzone_config = {}
    # make a copy of site_securityzone to modify
    site_securityzone_template = copy.deepcopy(config_site_securityzone)

    # perform name -> ID lookups
    name_lookup_in_template(site_securityzone_template, 'zone_id', securityzones_n2id)

    # replace complex names
    ssz_networks = site_securityzone_template.get('networks', None)
    if ssz_networks and isinstance(ssz_networks, list):
        ssz_networks_template = []
        for ssz_network in ssz_networks:
            ssz_network_template = copy.deepcopy(ssz_network)
            ssz_network_type = ssz_network.get('network_type')
            if ssz_network_type and ssz_network_type.lower() in ['wan_network', 'wan_overlay', 'lan_network']:
                if ssz_network_type.lower() == 'wan_network':
                    name_lookup_in_template(ssz_network_template, 'network_id', waninterface_n2id)
                elif ssz_network_type.lower() == 'wan_overlay':
                    name_lookup_in_template(ssz_network_template, 'network_id', wanoverlays_n2id)
                elif ssz_network_type.lower() == 'lan_network':
                    name_lookup_in_template(ssz_network_template, 'network_id', lannetworks_n2id)

            ssz_networks_template.append(ssz_network_template)
        site_securityzone_template['networks'] = ssz_networks_template

    local_debug("SITE_SECURITYZONE TEMPLATE: " + str(json.dumps(site_securityzone_template, indent=4)))

    # get current site_securityzone
    site_securityzone_resp = sdk.get.sitesecurityzones(site_id, site_securityzone_id)
    if site_securityzone_resp.cgx_status:
        site_securityzone_config = site_securityzone_resp.cgx_content
    else:
        throw_error("Unable to retrieve Site Securityzone: ", site_securityzone_resp)

    # extract prev_revision
    prev_revision = site_securityzone_config.get("_etag")

    # Check for changes:
    site_securityzone_change_check = copy.deepcopy(site_securityzone_config)
    site_securityzone_config.update(site_securityzone_template)
    if not force_update and site_securityzone_config == site_securityzone_change_check:
        # no change in config, pass.
        site_securityzone_id = site_securityzone_change_check.get('id')
        site_securityzone_zone_id = site_securityzone_resp.cgx_content.get('zone_id')
        # Try to get zone name this is for.
        ssz_zone_name = securityzones_id2n.get(site_securityzone_zone_id, site_securityzone_zone_id)
        output_message(" No Change for Site Securityzone mapping for {0}.".format(ssz_zone_name))
        return site_securityzone_id

    if debuglevel >= 3:
        local_debug("SITE_SECURITYZONE DIFF: {0}".format(find_diff(site_securityzone_change_check,
                                                                   site_securityzone_config)))

    # Update Site_securityzone.
    site_securityzone_resp2 = sdk.put.sitesecurityzones(site_id, site_securityzone_id, site_securityzone_config)

    if not site_securityzone_resp2.cgx_status:
        throw_error("Site Securityzone update failed: ", site_securityzone_resp2)

    site_securityzone_zone_id = site_securityzone_resp.cgx_content.get('zone_id')
    site_securityzone_id = site_securityzone_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = site_securityzone_resp2.cgx_content.get("_etag")

    if not site_securityzone_zone_id or not site_securityzone_id:
        throw_error("Unable to determine site securityzone attributes (ID {0}, Zone {1}).."
                    "".format(site_securityzone_id, site_securityzone_zone_id))

    # Try to get zone name this is for.
    ssz_zone_name = securityzones_id2n.get(site_securityzone_zone_id, site_securityzone_zone_id)

    output_message(" Updated Site Securityzone mapping for Zone '{0}' (Etag {1} -> {2})."
                   "".format(ssz_zone_name, prev_revision,current_revision))

    return site_securityzone_id


def delete_site_securityzones(leftover_site_securityzones, site_id, id2n=None):
    """
    Delete Site Securityzone Mappings
    :param leftover_site_securityzones: List of Site Securityzone IDs to delete
    :param site_id: Site ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for site_securityzone_id in leftover_site_securityzones:
        # delete all leftover site_securityzones.

        # Try to get zone name
        ssz_zone_name = securityzones_id2n.get(id2n.get(site_securityzone_id, site_securityzone_id),
                                               site_securityzone_id)

        output_message(" Deleting Unconfigured Site Securityzone mapping for Zone '{0}'."
                       "".format(ssz_zone_name))
        site_securityzone_del_resp = sdk.delete.sitesecurityzones(site_id, site_securityzone_id)
        if not site_securityzone_del_resp.cgx_status:
            throw_error("Could not delete Site Securityzone {0}: ".format(id2n.get(site_securityzone_id,
                                                                                   site_securityzone_id)),
                        site_securityzone_del_resp)
    return


def create_spokecluster(config_spokecluster, spokeclusters_n2id, site_id):
    """
    Create a Spoke Cluster
    :param config_spokecluster: Spoke Cluster config dict
    :param spokeclusters_n2id: Spoke Cluster Name to ID dict
    :param site_id: Site ID to use
    :return: New Spoke Cluster ID
    """
    # make a copy of spokecluster to modify
    spokecluster_template = copy.deepcopy(config_spokecluster)

    # perform name -> ID lookups
    # None needed for Spoke Clusters

    local_debug("SPOKECLUSTER TEMPLATE: " + str(json.dumps(spokecluster_template, indent=4)))

    # create spokecluster
    spokecluster_resp = sdk.post.spokeclusters(site_id, spokecluster_template)

    if not spokecluster_resp.cgx_status:
        throw_error("Spoke Cluster creation failed: ", spokecluster_resp)

    spokecluster_name = spokecluster_resp.cgx_content.get('name')
    spokecluster_id = spokecluster_resp.cgx_content.get('id')

    if not spokecluster_name or not spokecluster_id:
        throw_error("Unable to determine spokecluster attributes (Name: {0}, ID {1})..".format(spokecluster_name,
                                                                                               spokecluster_id))

    output_message(" Created Spoke Cluster {0}.".format(spokecluster_name))

    # update caches
    spokeclusters_n2id[spokecluster_name] = spokecluster_id

    return spokecluster_id


def modify_spokecluster(config_spokecluster, spokecluster_id, spokeclusters_n2id, site_id):
    """
    Modify Existing Spoke CLuster
    :param config_spokecluster: Spoke Cluster config dict
    :param spokecluster_id: Existing Spoke Cluster ID
    :param spokeclusters_n2id: Spoke Cluster Name to ID dict
    :param site_id: Site ID to use
    :return: Returned Spoke Cluster ID
    """
    spokecluster_config = {}
    # make a copy of spokecluster to modify
    spokecluster_template = copy.deepcopy(config_spokecluster)

    # perform name -> ID lookups
    # None needed for Spoke Clusters

    local_debug("SPOKECLUSTER TEMPLATE: " + str(json.dumps(spokecluster_template, indent=4)))

    # get current spokecluster
    spokecluster_resp = sdk.get.spokeclusters(site_id, spokecluster_id)
    if spokecluster_resp.cgx_status:
        spokecluster_config = spokecluster_resp.cgx_content
    else:
        throw_error("Unable to retrieve Spoke Cluster: ", spokecluster_resp)

    # extract prev_revision
    prev_revision = spokecluster_config.get("_etag")

    # Check for changes:
    spokecluster_change_check = copy.deepcopy(spokecluster_config)
    spokecluster_config.update(spokecluster_template)
    if not force_update and spokecluster_config == spokecluster_change_check:
        # no change in config, pass.
        spokecluster_id = spokecluster_change_check.get('id')
        spokecluster_name = spokecluster_change_check.get('name')
        output_message(" No Change for Spoke Cluster {0}.".format(spokecluster_name))
        return spokecluster_id

    if debuglevel >= 3:
        local_debug("SPOKECLUSTER DIFF: {0}".format(find_diff(spokecluster_change_check, spokecluster_config)))

    # Update spokecluster.
    spokecluster_resp2 = sdk.put.spokeclusters(site_id, spokecluster_id, spokecluster_config)

    if not spokecluster_resp2.cgx_status:
        throw_error("Spoke Cluster update failed: ", spokecluster_resp2)

    spokecluster_name = spokecluster_resp2.cgx_content.get('name')
    spokecluster_id = spokecluster_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = spokecluster_resp2.cgx_content.get("_etag")

    if not spokecluster_name or not spokecluster_id:
        throw_error("Unable to determine Spoke Cluster attributes (Name: {0}, ID {1})..".format(spokecluster_name,
                                                                                                spokecluster_id))

    output_message(" Updated Spoke Cluster {0} (Etag {1} -> {2}).".format(spokecluster_name, prev_revision,
                                                                          current_revision))

    # update caches
    spokeclusters_n2id[spokecluster_name] = spokecluster_id

    return spokecluster_id


def delete_spokeclusters(leftover_spokeclusters, site_id, id2n=None):
    """
    Delete Spoke Cluster
    :param leftover_spokeclusters: List of Spoke Cluster IDs to delete
    :param site_id: Site ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for spokecluster_id in leftover_spokeclusters:
        # delete all leftover spokeclusters.

        output_message(" Deleting Unconfigured Spoke Cluster {0}.".format(id2n.get(spokecluster_id, spokecluster_id)))
        spokecluster_del_resp = sdk.delete.spokeclusters(site_id, spokecluster_id)
        if not spokecluster_del_resp.cgx_status:
            throw_error("Could not delete Spoke Cluster {0}: ".format(id2n.get(spokecluster_id, spokecluster_id)),
                        spokecluster_del_resp)
    return


def create_interface(config_interface, interfaces_n2id, waninterfaces_n2id, lannetworks_n2id, site_id, element_id,
                     api_interfaces_cache=None, interfaces_funny_n2id=None):
    """
    Create a new Interface
    :param config_interface: Interface config dict
    :param interfaces_n2id: Interfaces Name to ID dict
    :param waninterfaces_n2id: WAN Interfaces Name to ID dict
    :param lannetworks_n2id: LAN Networks Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param api_interfaces_cache: Optional - Interface API cache, to be updated for some interface creations.
    :param interfaces_funny_n2id: Optional - Funny Name (eg: wrong name in config) Name to ID cache.
    :return: Created Interface ID
    """
    # interface cache is only needed for subifs.
    if api_interfaces_cache is None:
        api_interfaces_cache = []
    if interfaces_funny_n2id is None:
        interfaces_funny_n2id = {}
    update_api_interfaces_cache = False

    config_interface_type = config_interface.get('type')
    # validate this interface can be created.
    if config_interface_type not in createable_interface_types:
        throw_warning("Interface does not exist, and type {0} cannot be created.".format(config_interface.get('type')))
        # return empty
        return None

    # Create/modify flag. Certian interface configurations require a modify after create.
    # (Example, DHCP relay with source interface of self).
    create_modify = False
    # also create a holder for any config that needs stripped and re-added on modify.
    create_modify_config = {}

    # make a copy of interface to modify
    interface_template = copy.deepcopy(config_interface)

    # perform name -> ID lookups
    for key, value in config_interface.items():
        # if special values, do lookup.
        if key == "site_wan_interface_ids":
            n2id_swis = []
            # look for key in config, xlate name to ID.
            config_swi = config_interface.get('site_wan_interface_ids')
            if config_swi and isinstance(config_swi, list):
                for swi_name in config_swi:
                    n2id_swis.append(waninterfaces_n2id.get(swi_name, swi_name))

                # update template
                interface_template["site_wan_interface_ids"] = n2id_swis
            else:
                interface_template["site_wan_interface_ids"] = config_swi

        elif key == "attached_lan_networks":
            n2id_lns = []
            # look for key in config, xlate name to ID.
            config_ln = config_interface.get('attached_lan_networks', [])
            if config_ln and isinstance(config_ln, list):
                for ln_dict in config_ln:

                    ln_dict_template = copy.deepcopy(ln_dict)

                    ln_name = ln_dict.get('lan_network_id')
                    if ln_name:
                        ln_dict_template['lan_network_id'] = lannetworks_n2id.get(ln_name, ln_name)

                    n2id_lns.append(ln_dict_template)

                # update template
                interface_template["attached_lan_networks"] = n2id_lns
            else:
                interface_template["attached_lan_networks"] = config_ln

        elif key == "bypass_pair":

            # look for key in config, xlate name to ID.
            config_bpp = config_interface.get('bypass_pair', {})
            if config_bpp and isinstance(config_bpp, dict):
                # clone dict to modify
                n2id_bpp_template = copy.deepcopy(config_bpp)

                # replace names
                name_lookup_in_template(n2id_bpp_template, 'wan', interfaces_n2id)
                name_lookup_in_template(n2id_bpp_template, 'lan', interfaces_n2id)

                # update template
                interface_template["bypass_pair"] = n2id_bpp_template
            else:
                interface_template["bypass_pair"] = None

        elif key == "service_link_config":

            # look for key in config, xlate name to ID.
            config_servicelink = config_interface.get('service_link_config', {})
            if config_servicelink and isinstance(config_servicelink, dict):
                # clone dict to modify
                n2id_sl_template = copy.deepcopy(config_servicelink)

                # update nested dict
                config_ipsec = config_servicelink.get('ipsec_config', {})
                if config_ipsec and isinstance(config_ipsec, dict):
                    # clone dict to modify
                    n2id_ipsec_template = copy.deepcopy(config_ipsec)

                    name_lookup_in_template(n2id_ipsec_template, 'ipsec_profile_id', ipsecprofiles_n2id)

                    # update nested template
                    n2id_sl_template['ipsec_config'] = n2id_ipsec_template

                # replace flat names in dict
                name_lookup_in_template(n2id_sl_template, 'service_endpoint_id', serviceendpoints_n2id)

                # update template
                interface_template["service_link_config"] = n2id_sl_template
            else:
                interface_template["service_link_config"] = None

        elif key == "dhcp_relay":

            # look for key in config, xlate name to ID.
            config_dhcp_relay = config_interface.get('dhcp_relay', {})
            if config_dhcp_relay and isinstance(config_dhcp_relay, dict):
                # clone dict to modify
                n2id_dhcpr_template = copy.deepcopy(config_dhcp_relay)

                name_lookup_in_template(n2id_dhcpr_template, 'source_interface', interfaces_n2id)

                # Check for DHCP Relay set to use self during create.
                # if so, source interface in template will still be set to self name.
                source_interface = n2id_dhcpr_template.get('source_interface')
                if source_interface is not None and source_interface == interface_template.get('name'):
                    local_debug("IF create references self in DHCP relay config.", config_interface)
                    # DHCP source interface is referencing self. Save config for post create modify.
                    create_modify = True
                    create_modify_config["dhcp_relay"] = copy.deepcopy(n2id_dhcpr_template)
                    # set DHCP relay to None, will get picked up by post create modify.
                    n2id_dhcpr_template = None

                # update template
                interface_template["dhcp_relay"] = n2id_dhcpr_template
            else:
                interface_template["dhcp_relay"] = None

        else:
            # just set the key.
            interface_template[key] = value

    # replace flat names
    name_lookup_in_template(interface_template, 'parent', interfaces_n2id)

    # check for namable interfaces
    interface_template_name = interface_template.get('name')
    funny_name = None
    if config_interface_type not in nameable_interface_types:
        # need to strip name from template, save for later though.
        funny_name = interface_template.get('name')
        interface_template['name'] = None

    local_debug("INTERFACE TEMPLATE: " + str(json.dumps(interface_template, indent=4)))

    # For new bypasspairs, unconfgure parent interfaces.
    if config_interface_type == 'bypasspair':
        # modify lan and wan with default config.
        config_bypass_pair = interface_template.get('bypass_pair', None)
        if config_bypass_pair is None:
            throw_error("No bypass_pair config on bypasspair (Name: {0})..".format(interface_template_name))

        lan_if_id = config_bypass_pair.get('lan')
        wan_if_id = config_bypass_pair.get('wan')
        # if either don't exist throw error.
        if lan_if_id is None or wan_if_id is None:
            throw_error("WAN or LAN parent missing on bypasspair (Name: {0})..".format(interface_template_name))

        # ensure WAN and LAN bypasspair members are set default.
        default_template = get_member_default_config()
        output_message("   Setting Bypasspair parents for {0} to default.".format(interface_template_name))
        new_lan_id = modify_interface(default_template, lan_if_id, interfaces_n2id, waninterfaces_n2id,
                                      lannetworks_n2id, site_id, element_id)

        new_wan_id = modify_interface(default_template, wan_if_id, interfaces_n2id, waninterfaces_n2id,
                                      lannetworks_n2id, site_id, element_id)
    # For new pppoe, set parent to default.
    elif config_interface_type == 'pppoe':

        parent_if_id = interface_template.get('parent')
        if parent_if_id is None:
                throw_error("Parent missing on PPPoE interface (Name: {0})..".format(interface_template_name))

        # ensure WAN and LAN bypasspair members are set default.
        default_template = get_member_default_config()
        output_message("   Setting PPPoE parent for {0} to default.".format(interface_template_name))
        new_parent_id = modify_interface(default_template, parent_if_id, interfaces_n2id, waninterfaces_n2id,
                                         lannetworks_n2id, site_id, element_id)

    # For new subinterface, set parent to default if this is the FIRST SUBINTERFACE to use that parent.
    elif config_interface_type == 'subinterface':

        parent_if_id = interface_template.get('parent')
        if parent_if_id is None:
                throw_error("Parent missing on subinterface (Name: {0})..".format(interface_template_name))

        parent_already_used = check_api_subifs_for_parent(parent_if_id, api_interfaces_cache)

        if not parent_already_used:
            default_template = get_member_default_config()
            output_message("   Setting Subinterface parent for {0} to default.".format(interface_template_name))
            new_parent_id = modify_interface(default_template, parent_if_id, interfaces_n2id, waninterfaces_n2id,
                                             lannetworks_n2id, site_id, element_id)
            if new_parent_id:
                # if this is the first subif to use a parent if, we need to force update the cache at the end.
                update_api_interfaces_cache = True

    # create interface
    interface_resp = sdk.post.interfaces(site_id, element_id, interface_template)

    if not interface_resp.cgx_status:
        throw_error("Interface creation failed: ", interface_resp)

    interface_name = interface_resp.cgx_content.get('name')
    interface_id = interface_resp.cgx_content.get('id')

    if funny_name and funny_name != interface_name:
        if not interface_name or not interface_id:
            throw_error("Unable to determine interface attributes (Name: {0}({1}), ID {2})..".format(funny_name,
                                                                                                     interface_name,
                                                                                                     interface_id))

        output_message("   Created interface {0}({1}).".format(funny_name, interface_name))
    else:
        if not interface_name or not interface_id:
            throw_error("Unable to determine interface attributes (Name: {0}, ID {1})..".format(interface_name,
                                                                                                interface_id))

        output_message("   Created interface {0}.".format(interface_name))

    # update caches
    interfaces_n2id[interface_name] = interface_id
    if funny_name:
        interfaces_funny_n2id[funny_name] = interface_id
    # if a subif was created for the first time, the parent was defaulted. If parent was defaulted,
    # force update interface cache so we don't try to do it for the next subif created.
    if update_api_interfaces_cache:
        api_interfaces_cache.append(interface_resp.cgx_content)

    # check for create_modify flag. If so, we need to now do a modify.
    if create_modify:
        # kick off a subsequent modify to update the interface we just created.
        modify_interface_id = modify_interface(create_modify_config, interface_id, interfaces_n2id,
                                               waninterfaces_n2id, lannetworks_n2id,
                                               site_id, element_id, interfaces_funny_n2id=interfaces_funny_n2id)

        # shouldnt modify interface ID, but just in case..
        return modify_interface_id

    return interface_id


def modify_interface(config_interface, interface_id, interfaces_n2id, waninterfaces_n2id, lannetworks_n2id,
                     site_id, element_id, interfaces_funny_n2id=None):
    """
    Modify an existing interface
    :param config_interface: Interface config dict
    :param interface_id: Existing Interface ID
    :param interfaces_n2id: Interfaces Name to ID dict
    :param waninterfaces_n2id: WAN Interfaces Name to ID dict
    :param lannetworks_n2id: LAN Networks Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param interfaces_funny_n2id: Optional - Funny Name (eg: wrong name in config) Name to ID cache.
    :return: Returned Interface ID
    """
    if interfaces_funny_n2id is None:
        interfaces_funny_n2id = {}

    interface_config = {}
    config_interface_type = config_interface.get('type')
    # make a copy of interface to modify
    interface_template = copy.deepcopy(config_interface)

    # perform name -> ID lookups
    for key, value in config_interface.items():
        # if special values, do lookup.
        if key == "site_wan_interface_ids":
            n2id_swis = []
            # look for key in config, xlate name to ID.
            config_swi = config_interface.get('site_wan_interface_ids')
            if config_swi and isinstance(config_swi, list):
                for swi_name in config_swi:
                    n2id_swis.append(waninterfaces_n2id.get(swi_name, swi_name))

                # update template
                interface_template["site_wan_interface_ids"] = n2id_swis
            else:
                interface_template["site_wan_interface_ids"] = config_swi

        elif key == "attached_lan_networks":
            n2id_lns = []
            # look for key in config, xlate name to ID.
            config_ln = config_interface.get('attached_lan_networks', [])
            if config_ln and isinstance(config_ln, list):
                for ln_dict in config_ln:

                    ln_dict_template = copy.deepcopy(ln_dict)

                    ln_name = ln_dict.get('lan_network_id')
                    if ln_name:
                        ln_dict_template['lan_network_id'] = lannetworks_n2id.get(ln_name, ln_name)

                    n2id_lns.append(ln_dict_template)

                # update template
                interface_template["attached_lan_networks"] = n2id_lns
            else:
                interface_template["attached_lan_networks"] = None

        elif key == "bypass_pair":

            # look for key in config, xlate name to ID.
            config_bpp = config_interface.get('bypass_pair', {})
            if config_bpp and isinstance(config_bpp, dict):
                # clone dict to modify
                n2id_bpp_template = copy.deepcopy(config_bpp)

                # replace names
                name_lookup_in_template(n2id_bpp_template, 'wan', interfaces_n2id)
                name_lookup_in_template(n2id_bpp_template, 'lan', interfaces_n2id)

                # update template
                interface_template["bypass_pair"] = n2id_bpp_template
            else:
                interface_template["bypass_pair"] = None

        elif key == "service_link_config":

            # look for key in config, xlate name to ID.
            config_servicelink = config_interface.get('service_link_config', {})
            if config_servicelink and isinstance(config_servicelink, dict):
                # clone dict to modify
                n2id_sl_template = copy.deepcopy(config_servicelink)

                # update nested dict
                config_ipsec = config_servicelink.get('ipsec_config', {})
                if config_ipsec and isinstance(config_ipsec, dict):
                    # clone dict to modify
                    n2id_ipsec_template = copy.deepcopy(config_ipsec)

                    name_lookup_in_template(n2id_ipsec_template, 'ipsec_profile_id', ipsecprofiles_n2id)

                    # update nested template
                    n2id_sl_template['ipsec_config'] = n2id_ipsec_template

                # replace flat names in dict
                name_lookup_in_template(n2id_sl_template, 'service_endpoint_id', serviceendpoints_n2id)

                # update template
                interface_template["service_link_config"] = n2id_sl_template
            else:
                interface_template["service_link_config"] = None

        elif key == "dhcp_relay":

            # look for key in config, xlate name to ID.
            config_dhcp_relay = config_interface.get('dhcp_relay', {})
            if config_dhcp_relay and isinstance(config_dhcp_relay, dict):
                # clone dict to modify
                n2id_dhcpr_template = copy.deepcopy(config_dhcp_relay)

                name_lookup_in_template(n2id_dhcpr_template, 'source_interface', interfaces_n2id)

                # No need to check for self reference on modify, that is permissible.

                # update template
                interface_template["dhcp_relay"] = n2id_dhcpr_template
            else:
                interface_template["dhcp_relay"] = None

        else:
            # just set the key.
            interface_template[key] = value

    # replace flat names
    name_lookup_in_template(interface_template, 'parent', interfaces_n2id)

    # check for namable interfaces
    interface_template_name = interface_template.get('name')
    funny_name = None
    if config_interface_type not in nameable_interface_types:
        # need to strip name from template, save for later though.
        funny_name = interface_template.get('name')
        # for modify, overwrite and del the value in the template (force preserve of orig value)
        interface_template['name'] = None
        del interface_template['name']

    local_debug("INTERFACE TEMPLATE: " + str(json.dumps(interface_template, indent=4)))

    # get current interface
    interface_resp = sdk.get.interfaces(site_id, element_id, interface_id)
    if interface_resp.cgx_status:
        interface_config = interface_resp.cgx_content
    else:
        throw_error("Unable to retrieve interface: ", interface_resp)

    # extract prev_revision
    prev_revision = interface_config.get("_etag")

    # Check for changes:
    interface_change_check = copy.deepcopy(interface_config)
    interface_config.update(interface_template)
    if not force_update and interface_config == interface_change_check:
        # no change in config, pass.
        interface_id = interface_change_check.get('id')
        interface_name = interface_change_check.get('name')
        output_message("   No Change for Interface {0}.".format(interface_name))
        return interface_id

    if debuglevel >= 3:
        local_debug("INTERFACE DIFF: {0}".format(find_diff(interface_change_check, interface_config)))

    # Update Interface.
    interface_resp2 = sdk.put.interfaces(site_id, element_id, interface_id, interface_config)

    if not interface_resp2.cgx_status:
        throw_error("Interface update failed: ", interface_resp2)

    interface_name = interface_resp2.cgx_content.get('name')
    interface_id = interface_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = interface_resp2.cgx_content.get("_etag")

    if funny_name and funny_name != interface_name:
        if not interface_name or not interface_id:
            throw_error("Unable to determine interface attributes (Name: {0}({1}), ID {2})..".format(funny_name,
                                                                                                     interface_name,
                                                                                                     interface_id))

        output_message("   Updated Interface {0}({1}) (Etag {2} -> {3}).".format(funny_name, interface_name,
                                                                                 prev_revision, current_revision))
    else:
        if not interface_name or not interface_id:
            throw_error("Unable to determine interface attributes (Name: {0}, ID {1})..".format(interface_name,
                                                                                                interface_id))

        output_message("   Updated Interface {0} (Etag {1} -> {2}).".format(interface_name, prev_revision,
                                                                            current_revision))

    # update caches
    interfaces_n2id[interface_name] = interface_id
    if funny_name:
        interfaces_funny_n2id[funny_name] = interface_id

    return interface_id


def delete_interfaces(leftover_interfaces, site_id, element_id, id2n=None):
    """
    Delete a list of interfaces
    :param leftover_interfaces: List of Interface IDs to delete.
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for interface_id in leftover_interfaces:
        # delete all leftover interfaces.

        local_debug("INTERFACE ID", interface_id)

        output_message("   Deleting Unconfigured Interface {0}.".format(id2n.get(interface_id, interface_id)))
        interface_del_resp = sdk.delete.interfaces(site_id, element_id, interface_id)
        if not interface_del_resp.cgx_status:
            throw_error("Could not delete Interface {0}: ".format(id2n.get(interface_id, interface_id)),
                        interface_del_resp)
    return


def get_config_interfaces_by_type(config_interfaces, type_str):
    """
    Extract config entries from dict by type
    :param config_interfaces: Interfaces config dict
    :param type_str: Type string to match
    :return: Interfaces config dict only containing type matching type_str
    """
    config_template = {}
    for name, config_interface in config_interfaces.items():
        if config_interface.get('type') == type_str:
            config_template[name] = copy.deepcopy(config_interface)

    return config_template


def get_api_interfaces_by_type(api_interfaces, type_str):
    """
    Extract Interface API responses by type
    :param api_interfaces: Interface API response
    :param type_str: Type string to match
    :return: Interfaces API response dict only containing type matching type_str
    """
    interface_list = []
    for interface in api_interfaces:
        if interface.get('type') == type_str:
            interface_list.append(interface)

    return interface_list


def get_config_interfaces_name_by_type(config_interfaces, type_str):
    """
    Extract interface names matching specific type from Interface config
    :param config_interfaces: Interfaces config dict
    :param type_str: Type string to match
    :return: List of Interface names matching type_str
    """
    interface_name_list = []
    for name, config_interface in config_interfaces.items():
        if config_interface.get('type') == type_str:
            interface_name_list.append(name)

    return interface_name_list


def get_api_interfaces_name_by_type(api_interfaces, type_str, key_name='name'):
    """
    Extract interface names from Interfaces API response by type
    :param api_interfaces: Interfaces API response
    :param type_str: Type string to match
    :param key_name: Optional - Key name to use (default 'name')
    :return: List of Interface names matching type_str
    """
    interface_name_list = []
    for interface in api_interfaces:
        if_name = interface.get(key_name)
        if if_name and interface.get('type') == type_str:
            interface_name_list.append(if_name)

    return interface_name_list


def get_loopback_lists(config_interfaces, interfaces_cache, interfaces_n2id):
    """
    Loopback handling. Sadly pretty complex.

    Logic - Loopbacks have no settable determinstic name. Name is created based on Unique ID generated at creation.
        We have to handle these somehow. We use Date of creation.

    Order existing loopbacks by date of creation. Order config file loopbacks by numerical trailer order (eg: loopback1,
        loopback2, etc.)

    Oldest loopback on API maps to lowest numbered config interface. This should generally line up loopbacks in configs
        to what exists in API.

    :param config_interfaces: Config Interfaces dict
    :param interfaces_cache: Interfaces API response cache
    :param interfaces_n2id: Interfaces Name to ID Map.
    :return: Tuple of Loopbacks to be added config, List of all existing loopback IDs,
                Config Loopback names to IDs dict (when mappings can be made, example of a "funny name")
    """

    # Compare loopback interfaces - Because loopback names are ID based, we can only compare count of
    # loopback + order of creation. Detect and sort, and create/modify existing as needed.
    add_loopback_list = []
    delete_loopback_list = []
    config_loopback_n2id = {}
    config_ifname_loopback = order_interface_by_number(get_config_interfaces_name_by_type(
        config_interfaces, 'loopback'))
    interfaces_loopback_list = order_interface_by_number(get_api_interfaces_name_by_type(
        interfaces_cache, 'loopback'))

    config_len = len(config_ifname_loopback)
    api_len = len(interfaces_loopback_list)

    if config_len > api_len:
        # More loopbacks in config than exist on element, queue for creation
        add_loopback_list = config_ifname_loopback[len(interfaces_loopback_list):]
    elif config_len < api_len:
        # More loopbacks on element than in config, queue for deletion
        delete_loopback_list = interfaces_loopback_list[len(config_ifname_loopback):]

    # deletes queued for later, add for loopback need to be done now in case
    # they are needed for bypasspairs.

    config_loopback_add = dict((k, v) for (k, v) in config_interfaces.items() if k in add_loopback_list)
    leftover_loopbacks = [value for value in interfaces_cache if
                          value.get('name') in delete_loopback_list]

    # create loopback config_name (funny_name) to matching real interface ID mapping
    for idx, value in enumerate(interfaces_loopback_list):
        if idx < config_len:
            if_id = interfaces_n2id.get(value)
            if if_id:
                config_loopback_n2id[config_ifname_loopback[idx]] = if_id

    return config_loopback_add, leftover_loopbacks, config_loopback_n2id


def get_pppoe_id(config_pppoe_interface, interfaces_cache, interfaces_n2id):
    """
    PPPoE interfaces are determined based on parent config. Each parent can only have one PPPoE.
    :param config_pppoe_interface: PPPoE Interface config entry
    :param interfaces_cache: Interfaces API Response cache
    :param interfaces_n2id: Interfaces Name to ID dict
    :return: Matching PPPoE Interface ID
    """
    return_if_id = None
    parent_if_id = interfaces_n2id.get(config_pppoe_interface.get('parent', ""))

    if parent_if_id is None:
        throw_error("PPPoE Interface {0} config is missing 'parent': ".format(config_pppoe_interface.get('name')),
                    config_pppoe_interface)
    for interface in interfaces_cache:
        # check for parent match.
        if interface.get('parent') == parent_if_id:
            return_if_id = interface.get('id')

    return return_if_id


def get_subif_id(config_subif_interface, interfaces_cache, interfaces_n2id):
    """
    Look up Sub Interface ID, using parent in config and VLAN ID as the identifiers.
    :param config_subif_interface: Interfaces (Subinterfaces only) config dict.
    :param interfaces_cache: Interfaces API response cache
    :param interfaces_n2id: Interfaces Name to ID dict
    :return: Matching SubInterface ID
    """
    return_if_id = None
    parent_if_id = interfaces_n2id.get(config_subif_interface.get('parent', ""))
    if parent_if_id is None:
        throw_error("Subinterface {0} config is missing 'parent': ".format(config_subif_interface.get('name')),
                    config_subif_interface)

    subinterface_dict = config_subif_interface.get('sub_interface', {})
    if subinterface_dict is None:
        throw_error("Subinterface {0} config is missing 'sub_interface': ".format(config_subif_interface.get('name')),
                    config_subif_interface)

    vlan_id = subinterface_dict.get('vlan_id')
    if vlan_id is None:
        throw_error("Subinterface {0} 'sub_interface' section is missing 'vlan_id': "
                    "".format(config_subif_interface.get('name')),
                    config_subif_interface)

    # subif names consist of parent.vlan, and cannot be modified. lookup by parent.id instead of name.
    for interface in interfaces_cache:
        # check for parent match.
        subinterface_dict_cache = interface.get('sub_interface')
        if interface.get('parent') == parent_if_id and subinterface_dict_cache:
            # got values for both, validate VLAN.
            if subinterface_dict_cache.get('vlan_id') == vlan_id:
                # Parent and VLAN ID match. This is the subinterface in config. Set the ID.
                return_if_id = interface.get('id')

    return return_if_id


def get_parent_child_dict(config_interfaces, id2n=None):
    """
    Create parent/child relationship dicts for Interfaces.
    :param config_interfaces: Interfaces config dict
    :param id2n: Optional - ID to Name lookup dict
    :return: Tuple of Parent name to child name list dict, Child name to parent name list dict
    """
    if id2n is None:
        id2n = {}

    used_parent_name_list = []
    parent_if_map = {}
    child_if_map = {}

    for config_interfaces_name, config_interfaces_value in config_interfaces.items():
        config_interfaces_type = config_interfaces_value.get('type')
        if config_interfaces_type is None:
            throw_error("Interface {0} is missing 'type' field:".format(config_interfaces_name),
                        config_interfaces_value)

        # handle each child if type.
        if config_interfaces_type == 'bypasspair':
            bypasspair_dict = config_interfaces_value.get('bypass_pair', {})
            if bypasspair_dict is None:
                throw_error("Bypass pair {0} is missing bypass info:".format(config_interfaces_name),
                            config_interfaces_value)

            bypasspair_wan = bypasspair_dict.get('wan')
            bypasspair_lan = bypasspair_dict.get('lan')
            bypasspair_wan_name = id2n.get(bypasspair_wan, bypasspair_wan)
            bypasspair_lan_name = id2n.get(bypasspair_lan, bypasspair_lan)

            if bypasspair_wan_name in used_parent_name_list or bypasspair_lan_name in used_parent_name_list:
                # used multiple times.
                throw_error("Bypass pair {0} is using a port that is a parent of another interface:"
                            "".format(config_interfaces_name),
                            config_interfaces_value)

            # no duplicates, update parent map (bypasspairs many parent, one child).
            parent_if_map[bypasspair_wan_name] = [config_interfaces_name]
            parent_if_map[bypasspair_lan_name] = [config_interfaces_name]
            child_if_map[config_interfaces_name] = [bypasspair_wan_name, bypasspair_lan_name]
            used_parent_name_list.append(bypasspair_wan_name)
            used_parent_name_list.append(bypasspair_lan_name)

        elif config_interfaces_type == 'subinterface':
            parent_if = config_interfaces_value.get('parent')
            if parent_if is None:
                throw_error("Subinterface {0} is missing 'parent' field:".format(config_interfaces_name),
                            config_interfaces_value)

            parent_if_name = id2n.get(parent_if, parent_if)

            # subinterfaces can handle many children, one parent
            existing_children = parent_if_map.get(config_interfaces_name)
            if existing_children is None:
                parent_if_map[parent_if_name] = [config_interfaces_name]
            else:
                new_children = list(existing_children)
                new_children.append(config_interfaces_name)
                parent_if_map[parent_if_name] = new_children

            child_if_map[config_interfaces_name] = parent_if_name
            used_parent_name_list.append(parent_if_name)

        elif config_interfaces_type == 'pppoe':
            parent_if = config_interfaces_value.get('parent')
            if parent_if is None:
                throw_error("PPPoE interface {0} is missing 'parent' field:".format(config_interfaces_name),
                            config_interfaces_value)

            parent_if_name = id2n.get(parent_if, parent_if)

            if parent_if_name in used_parent_name_list:
                # used multiple times.
                throw_error("PPPoE interface {0} is using a port that is a parent of another interface:"
                            "".format(config_interfaces_name),
                            config_interfaces_value)

            # PPPoE should be in both child and parent
            parent_if_map[parent_if_name] = [config_interfaces_name]
            child_if_map[config_interfaces_name] = [parent_if_name]
            used_parent_name_list.append(parent_if_name)

        # Note, service_link parents can be configured, so they are not done here.

    return parent_if_map, child_if_map


def get_bypass_id_from_name(bypass_name, interfaces_n2id, funny_n2id=None):
    """
    Get Bypasspair Interface ID from explicit name. Handle reverse mappings, as name can be reversed.
    :param bypass_name: String to look up
    :param interfaces_n2id: Interfaces Name to ID Map
    :param funny_n2id: Funny (incorrect, un-renamable) Interfaces Name to ID map
    :return: Bypasspair Interface ID, if found.
    """

    # Make sure all possible IFs are accounted for in the name lookup.
    comprehensive_bypasspair_names = copy.deepcopy(bypasspair_child_names)
    # extend the list with the names in the n2id lists.
    if funny_n2id is not None:
        comprehensive_bypasspair_names.extend(funny_n2id.keys())
    # apply interfaces 2nd as it should trump funny names.
    comprehensive_bypasspair_names.extend(interfaces_n2id.keys())


    return_id = interfaces_n2id.get(bypass_name)
    if return_id is None and funny_n2id is not None:
        # check funny name cache
        return_id = funny_n2id.get(bypass_name)

    # still none, do some reverse checks.
    if return_id is None:
        for part1 in comprehensive_bypasspair_names:
            for part2 in comprehensive_bypasspair_names:
                if part1 + part2 == bypass_name:
                    # check for reverse ID
                    id_check = interfaces_n2id.get(part2 + part1)
                    if id_check is not None:
                        return_id = id_check
                        local_debug("BYPASS REVERSE HIT: {0}: {1}".format(part2 + part1, return_id))

    # still none, leave debug.
    if return_id is None:
        local_debug("BYPASS NAME MISS: {0}: {1}".format(bypass_name, return_id))
    else:
        # already matched, show hit
        local_debug("BYPASS FORWARD HIT: {0}: {1}".format(bypass_name, return_id))

    return return_id


def get_bypass_id_from_parent(bypass_pair, api_interfaces, interfaces_n2id, funny_n2id=None):
    """
    Get Bypasspair Interface ID parents.
    :param bypass_pair: Bypass Pair object to look up.
    :param api_interfaces: Interfaces retrieved from API. Ideally should be only bypasspairs.
    :param interfaces_n2id: Interfaces Name to ID Map
    :param funny_n2id: Funny (incorrect, un-renamable) Interfaces Name to ID map
    :return: Bypasspair Interface ID, if found.
    """

    return_id = None
    interfaces_local_n2id = {}

    # funny name handling
    if funny_n2id is not None:
        interfaces_local_n2id.update(funny_n2id)
    # normal name handling
    interfaces_local_n2id.update(interfaces_n2id)

    # extract WAN/LAN objects
    config_wan_name = bypass_pair.get('wan')
    config_lan_name = bypass_pair.get('lan')
    config_wan = interfaces_local_n2id.get(config_wan_name)
    config_lan = interfaces_local_n2id.get(config_lan_name)

    if config_lan is None or config_wan is None:
        # return, can't succeed without Interface IDs for each parent.
        local_debug("NO WAN AND/OR LAN IN BYPASS_PAIR: WAN {0}:{1} LAN {2}:{3}"
                    "".format(config_wan_name, config_wan, config_lan_name, config_lan))
        return return_id
    for api_interface in api_interfaces:
        api_bypass_pair = api_interface.get('bypass_pair')
        api_id = api_interface.get('id')
        if api_id and api_bypass_pair is not None and isinstance(api_bypass_pair, dict):
            # valid BP object, check
            api_wan = api_bypass_pair.get('wan')
            api_lan = api_bypass_pair.get('lan')
            if config_wan == api_wan and config_lan == api_lan:
                # Hit
                local_debug("BYPASS ID_FROM_PARENT HIT: {0}".format(api_id))
                return_id = api_id

    # return
    return return_id


def check_api_subifs_for_parent(interface_id, interfaces_cache):
    """
    Check for existing subinterfaces on an interface ID
    :param interface_id: Interface ID to check
    :param interfaces_cache: Interfaces API Response cache
    :return: Bool, True if active Subinterfaces.
    """
    active_subifs = False
    for interface in interfaces_cache:
        if interface.get('type') == 'subinterface':
            if interface.get('parent') == interface_id:
                # found a match!
                active_subifs = True
                return active_subifs

    return active_subifs


def create_staticroute(config_staticroute, interfaces_n2id, site_id, element_id):
    """
    Create a new Static Route
    :param config_staticroute: Static Route config dict
    :param interfaces_n2id: Interfaces Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Created Static Route ID
    """
    # make a copy of staticroute to modify
    staticroute_template = copy.deepcopy(config_staticroute)

    # perform name -> ID lookups
    for key, value in config_staticroute.items():
        # if special values, do lookup.
        if key == "nexthops":
            n2id_ifs = []
            # look for key in config, xlate name to ID.
            config_nh = config_staticroute.get('nexthops', [])
            if config_nh and isinstance(config_nh, list):
                for nh_dict in config_nh:

                    nh_dict_template = copy.deepcopy(nh_dict)

                    nhr_name = nh_dict.get('nexthop_interface_id')
                    if nhr_name:
                        nh_dict_template['nexthop_interface_id'] = interfaces_n2id.get(nhr_name, nhr_name)

                    n2id_ifs.append(nh_dict_template)

                # update template
                staticroute_template["nexthops"] = n2id_ifs
            else:
                staticroute_template["nexthops"] = config_nh

        else:
            # just set the key.
            staticroute_template[key] = value

    # replace flat names
    name_lookup_in_template(staticroute_template, 'network_context_id', networkcontexts_n2id)

    local_debug("STATICROUTE TEMPLATE: " + str(json.dumps(staticroute_template, indent=4)))

    # create staticroute
    staticroute_resp = sdk.post.staticroutes(site_id, element_id, staticroute_template)

    if not staticroute_resp.cgx_status:
        throw_error("Staticroute creation failed: ", staticroute_resp)

    staticroute_id = staticroute_resp.cgx_content.get('id')

    if not staticroute_id:
        throw_error("Unable to determine staticroute attributes (ID {0})..".format(staticroute_id))

    output_message("   Created staticroute {0}.".format(staticroute_id))

    return staticroute_id


def modify_staticroute(config_staticroute, staticroute_id, interfaces_n2id,
                       site_id, element_id):
    """
    Modify an existing Static route
    :param config_staticroute: Static Route config dict
    :param staticroute_id: ID of existing Static Route
    :param interfaces_n2id: Interfaces Name to ID Map
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Returned Static Route ID.
    """
    staticroute_config = {}
    # make a copy of staticroute to modify
    staticroute_template = copy.deepcopy(config_staticroute)

    # perform name -> ID lookups
    for key, value in config_staticroute.items():
        # if special values, do lookup.
        if key == "nexthops":
            n2id_ifs = []
            # look for key in config, xlate name to ID.
            config_nh = config_staticroute.get('nexthops', [])
            if config_nh and isinstance(config_nh, list):
                for nh_dict in config_nh:

                    nh_dict_template = copy.deepcopy(nh_dict)

                    nhr_name = nh_dict.get('nexthop_interface_id')
                    if nhr_name:
                        nh_dict_template['nexthop_interface_id'] = interfaces_n2id.get(nhr_name, nhr_name)

                    n2id_ifs.append(nh_dict_template)

                # update template
                staticroute_template["nexthops"] = n2id_ifs
            else:
                staticroute_template["nexthops"] = config_nh

        else:
            # just set the key.
            staticroute_template[key] = value

    # replace flat names
    name_lookup_in_template(staticroute_template, 'network_context_id', networkcontexts_n2id)

    local_debug("STATICROUTE TEMPLATE: " + str(json.dumps(staticroute_template, indent=4)))

    # get current staticroute
    staticroute_resp = sdk.get.staticroutes(site_id, element_id, staticroute_id)
    if staticroute_resp.cgx_status:
        staticroute_config = staticroute_resp.cgx_content
    else:
        throw_error("Unable to retrieve staticroute: ", staticroute_resp)

    # extract prev_revision
    prev_revision = staticroute_config.get("_etag")

    # Check for changes:
    staticroute_change_check = copy.deepcopy(staticroute_config)
    staticroute_config.update(staticroute_template)
    if not force_update and staticroute_config == staticroute_change_check:
        # no change in config, pass.
        staticroute_id = staticroute_change_check.get('id')
        staticroute_name = staticroute_change_check.get('name')
        output_message("   No Change for Staticroute {0}.".format(staticroute_id))
        return staticroute_id

    if debuglevel >= 3:
        local_debug("STATICROUTE DIFF: {0}".format(find_diff(staticroute_change_check, staticroute_config)))

    # Update Staticroute.
    staticroute_resp2 = sdk.put.staticroutes(site_id, element_id, staticroute_id, staticroute_config)

    if not staticroute_resp2.cgx_status:
        throw_error("Staticroute update failed: ", staticroute_resp2)

    staticroute_id = staticroute_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = staticroute_resp2.cgx_content.get("_etag")

    if not staticroute_id:
        throw_error("Unable to determine staticroute attributes (ID {0})..".format(staticroute_id))

    output_message("   Updated Staticroute {0} (Etag {1} -> {2}).".format(staticroute_id, prev_revision,
                                                                          current_revision))

    return staticroute_id


def delete_staticroutes(leftover_staticroutes, site_id, element_id, id2n=None):
    """
    Delete a list of Static Routes
    :param leftover_staticroutes: List of Static Route IDs
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for staticroute_id in leftover_staticroutes:
        # delete all leftover staticroutes.

        output_message("   Deleting Unconfigured Staticroute {0}.".format(id2n.get(staticroute_id, staticroute_id)))
        staticroute_del_resp = sdk.delete.staticroutes(site_id, element_id, staticroute_id)
        if not staticroute_del_resp.cgx_status:
            throw_error("Could not delete Staticroute {0}: ".format(id2n.get(staticroute_id, staticroute_id)),
                        staticroute_del_resp)
    return


def create_aspath_access_list(config_aspath_access_list, aspath_access_list_n2id, site_id, element_id):
    """
    Create a new Routing AS-Path Access List
    :param config_aspath_access_list: AS-Path Access list config
    :param aspath_access_list_n2id: AS-Path Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: New AS-Path ACL ID
    """
    # make a copy of aspath_access_list to modify
    aspath_access_list_template = copy.deepcopy(config_aspath_access_list)

    local_debug("aspath_access_list TEMPLATE: " + str(json.dumps(aspath_access_list_template, indent=4)))

    # create aspath_access_list
    aspath_access_list_resp = sdk.post.routing_aspathaccesslists(site_id, element_id, aspath_access_list_template)

    if not aspath_access_list_resp.cgx_status:
        throw_error("AS-PATH Access List creation failed: ", aspath_access_list_resp)

    aspath_access_list_id = aspath_access_list_resp.cgx_content.get('id')
    aspath_access_list_name = aspath_access_list_resp.cgx_content.get('name', aspath_access_list_id)

    if not aspath_access_list_id:
        throw_error("Unable to determine AS-PATH Access List ({0})..".format(aspath_access_list_name),
                    aspath_access_list_resp)

    output_message("   Created AS-PATH Access List {0}.".format(aspath_access_list_name))

    # update caches
    aspath_access_list_n2id[aspath_access_list_name] = aspath_access_list_id

    return aspath_access_list_id


def modify_aspath_access_list(config_aspath_access_list, aspath_access_list_id, aspath_access_list_n2id,
                              site_id, element_id):
    """
    Modify an existing Routing AS-Path Access List
    :param config_aspath_access_list: AS-Path Access list config
    :param aspath_access_list_id: Existing AS-Path ACL ID
    :param aspath_access_list_n2id: AS-Path Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Returned AS-Path ACL ID
    """
    aspath_access_list_config = {}
    # make a copy of aspath_access_list to modify
    aspath_access_list_template = copy.deepcopy(config_aspath_access_list)

    local_debug("aspath_access_list TEMPLATE: " + str(json.dumps(aspath_access_list_template, indent=4)))

    # get current aspath_access_list
    aspath_access_list_resp = sdk.get.routing_aspathaccesslists(site_id, element_id, aspath_access_list_id)
    if aspath_access_list_resp.cgx_status:
        aspath_access_list_config = aspath_access_list_resp.cgx_content
    else:
        throw_error("Unable to retrieve AS-PATH Access List: ", aspath_access_list_resp)

    # extract prev_revision
    prev_revision = aspath_access_list_config.get("_etag")

    # Check for changes:
    aspath_access_list_change_check = copy.deepcopy(aspath_access_list_config)
    aspath_access_list_config.update(aspath_access_list_template)
    if not force_update and aspath_access_list_config == aspath_access_list_change_check:
        # no change in config, pass.
        aspath_access_list_id = aspath_access_list_change_check.get('id')
        aspath_access_list_name = aspath_access_list_change_check.get('name')
        output_message("   No Change for AS-PATH Access List {0}.".format(aspath_access_list_name))
        return aspath_access_list_id

    if debuglevel >= 3:
        local_debug("aspath_access_list DIFF: {0}".format(find_diff(aspath_access_list_change_check,
                                                                    aspath_access_list_config)))

    # Update aspath_access_list.
    aspath_access_list_resp2 = sdk.put.aspath_access_lists(site_id, element_id, aspath_access_list_id,
                                                           aspath_access_list_config)

    if not aspath_access_list_resp2.cgx_status:
        throw_error("AS-PATH Access List failed: ", aspath_access_list_resp2)

    aspath_access_list_id = aspath_access_list_resp2.cgx_content.get('id')
    aspath_access_list_name = aspath_access_list_resp2.cgx_content.get('name', aspath_access_list_id)

    # extract current_revision
    current_revision = aspath_access_list_resp2.cgx_content.get("_etag")

    if not aspath_access_list_id:
        throw_error("Unable to determine AS-PATH Access List attributes ({0})..".format(aspath_access_list_name),
                    aspath_access_list_resp2)

    output_message("   Updated AS-PATH Access List {0} (Etag {1} -> {2}).".format(aspath_access_list_name,
                                                                                  prev_revision,
                                                                                  current_revision))

    # update caches
    aspath_access_list_n2id[aspath_access_list_name] = aspath_access_list_id

    return aspath_access_list_id


def delete_aspath_access_lists(leftover_aspath_access_lists, site_id, element_id, id2n=None):
    """
    Delete AS-Path Access lists
    :param leftover_aspath_access_lists: List of AS-Path ACLs to delete
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for aspath_access_list_id in leftover_aspath_access_lists:
        # delete all leftover aspath_access_lists.

        output_message("   Deleting Unconfigured AS-PATH Access List {0}.".format(id2n.get(aspath_access_list_id,
                                                                                           aspath_access_list_id)))
        aspath_access_list_del_resp = sdk.delete.routing_aspathaccesslists(site_id, element_id, aspath_access_list_id)
        if not aspath_access_list_del_resp.cgx_status:
            throw_error("Could not delete AS-PATH Access List {0}: ".format(id2n.get(aspath_access_list_id,
                                                                                     aspath_access_list_id)),
                        aspath_access_list_del_resp)
    return


def create_ip_community_list(config_ip_community_list, ip_community_list_n2id, site_id, element_id):

    """
    Create an IP Community List
    :param config_ip_community_list: IP Community list config dict
    :param ip_community_list_n2id: IP Community List Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Created IP Community List ID
    """
    # make a copy of ip_community_list to modify
    ip_community_list_template = copy.deepcopy(config_ip_community_list)

    local_debug("ip_community_list TEMPLATE: " + str(json.dumps(ip_community_list_template, indent=4)))

    # create ip_community_list
    ip_community_list_resp = sdk.post.routing_ipcommunitylists(site_id, element_id, ip_community_list_template)

    if not ip_community_list_resp.cgx_status:
        throw_error("IP Community List creation failed: ", ip_community_list_resp)

    ip_community_list_id = ip_community_list_resp.cgx_content.get('id')
    ip_community_list_name = ip_community_list_resp.cgx_content.get('name', ip_community_list_id)

    if not ip_community_list_id:
        throw_error("Unable to determine IP Community List ({0})..".format(ip_community_list_name),
                    ip_community_list_resp)

    output_message("   Created IP Community List {0}.".format(ip_community_list_name))

    # update caches
    ip_community_list_n2id[ip_community_list_name] = ip_community_list_id

    return ip_community_list_id


def modify_ip_community_list(config_ip_community_list, ip_community_list_id, ip_community_list_n2id,
                             site_id, element_id):
    """
    Modify an existing IP Community List
    :param config_ip_community_list: IP Community list config dict
    :param ip_community_list_id: Existing IP Community list ID
    :param ip_community_list_n2id: IP Community List Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: None
    """
    ip_community_list_config = {}
    # make a copy of ip_community_list to modify
    ip_community_list_template = copy.deepcopy(config_ip_community_list)

    local_debug("ip_community_list TEMPLATE: " + str(json.dumps(ip_community_list_template, indent=4)))

    # get current ip_community_list
    ip_community_list_resp = sdk.get.routing_ipcommunitylists(site_id, element_id, ip_community_list_id)
    if ip_community_list_resp.cgx_status:
        ip_community_list_config = ip_community_list_resp.cgx_content
    else:
        throw_error("Unable to retrieve IP Community List: ", ip_community_list_resp)

    # extract prev_revision
    prev_revision = ip_community_list_config.get("_etag")

    # Check for changes:
    ip_community_list_change_check = copy.deepcopy(ip_community_list_config)
    ip_community_list_config.update(ip_community_list_template)
    if not force_update and ip_community_list_config == ip_community_list_change_check:
        # no change in config, pass.
        ip_community_list_id = ip_community_list_change_check.get('id')
        ip_community_list_name = ip_community_list_change_check.get('name')
        output_message("   No Change for IP Community List {0}.".format(ip_community_list_name))
        return ip_community_list_id

    if debuglevel >= 3:
        local_debug("ip_community_list DIFF: {0}".format(find_diff(ip_community_list_change_check,
                                                                   ip_community_list_config)))

    # Update ip_community_list.
    ip_community_list_resp2 = sdk.put.ip_community_lists(site_id, element_id, ip_community_list_id,
                                                         ip_community_list_config)

    if not ip_community_list_resp2.cgx_status:
        throw_error("IP Community List failed: ", ip_community_list_resp2)

    ip_community_list_id = ip_community_list_resp2.cgx_content.get('id')
    ip_community_list_name = ip_community_list_resp2.cgx_content.get('name', ip_community_list_id)

    # extract current_revision
    current_revision = ip_community_list_resp2.cgx_content.get("_etag")

    if not ip_community_list_id:
        throw_error("Unable to determine IP Community List attributes ({0})..".format(ip_community_list_name),
                    ip_community_list_resp2)

    output_message("   Updated IP Community List {0} (Etag {1} -> {2}).".format(ip_community_list_name,
                                                                                prev_revision,
                                                                                current_revision))

    # update caches
    ip_community_list_n2id[ip_community_list_name] = ip_community_list_id

    return ip_community_list_id


def delete_ip_community_lists(leftover_ip_community_lists, site_id, element_id, id2n=None):
    """
    Delete a list of IP Community Lists
    :param leftover_ip_community_lists: List of IP Community List IDs to delete
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for ip_community_list_id in leftover_ip_community_lists:
        # delete all leftover ip_community_lists.

        output_message("   Deleting Unconfigured IP Community List {0}.".format(id2n.get(ip_community_list_id,
                                                                                         ip_community_list_id)))
        ip_community_list_del_resp = sdk.delete.routing_ipcommunitylists(site_id, element_id, ip_community_list_id)
        if not ip_community_list_del_resp.cgx_status:
            throw_error("Could not delete IP Community List {0}: ".format(id2n.get(ip_community_list_id,
                                                                                   ip_community_list_id)),
                        ip_community_list_del_resp)
    return


def create_prefixlist(config_prefixlist, prefixlist_n2id, site_id, element_id):
    """
    Create Routing Prefix List
    :param config_prefixlist: Routing Prefix List config dict
    :param prefixlist_n2id: Routing Prefix List Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Created Routing Prefixlist ID
    """
    # make a copy of prefixlist to modify
    prefixlist_template = copy.deepcopy(config_prefixlist)

    local_debug("prefixlist TEMPLATE: " + str(json.dumps(prefixlist_template, indent=4)))

    # create prefixlist
    prefixlist_resp = sdk.post.routing_prefixlists(site_id, element_id, prefixlist_template)

    if not prefixlist_resp.cgx_status:
        throw_error("Routing Prefixlist creation failed: ", prefixlist_resp)

    prefixlist_id = prefixlist_resp.cgx_content.get('id')
    prefixlist_name = prefixlist_resp.cgx_content.get('name', prefixlist_id)

    if not prefixlist_id:
        throw_error("Unable to determine Routing Prefixlist ({0})..".format(prefixlist_name), prefixlist_resp)

    output_message("   Created Routing Prefixlist {0}.".format(prefixlist_name))

    # update caches
    prefixlist_n2id[prefixlist_name] = prefixlist_id

    return prefixlist_id


def modify_prefixlist(config_prefixlist, prefixlist_id, prefixlist_n2id, site_id, element_id):
    """
    Modify Existing Routing Prefix List
    :param config_prefixlist: Routing Prefix List config dict
    :param prefixlist_id: Existing Routing Prefix list ID
    :param prefixlist_n2id: Routing Prefix List Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Returned Routing Prefixlist ID
    """
    prefixlist_config = {}
    # make a copy of prefixlist to modify
    prefixlist_template = copy.deepcopy(config_prefixlist)

    local_debug("prefixlist TEMPLATE: " + str(json.dumps(prefixlist_template, indent=4)))

    # get current prefixlist
    prefixlist_resp = sdk.get.routing_prefixlists(site_id, element_id, prefixlist_id)
    if prefixlist_resp.cgx_status:
        prefixlist_config = prefixlist_resp.cgx_content
    else:
        throw_error("Unable to retrieve Routing Prefixlist: ", prefixlist_resp)

    # extract prev_revision
    prev_revision = prefixlist_config.get("_etag")

    # Check for changes:
    prefixlist_change_check = copy.deepcopy(prefixlist_config)
    prefixlist_config.update(prefixlist_template)
    if not force_update and prefixlist_config == prefixlist_change_check:
        # no change in config, pass.
        prefixlist_id = prefixlist_change_check.get('id')
        prefixlist_name = prefixlist_change_check.get('name')
        output_message("   No Change for Routing Prefixlist {0}.".format(prefixlist_name))
        return prefixlist_id

    if debuglevel >= 3:
        local_debug("prefixlist DIFF: {0}".format(find_diff(prefixlist_change_check, prefixlist_config)))

    # Update prefixlist.
    prefixlist_resp2 = sdk.put.routing_prefixlists(site_id, element_id, prefixlist_id, prefixlist_config)

    if not prefixlist_resp2.cgx_status:
        throw_error("Routing Prefixlist failed: ", prefixlist_resp2)

    prefixlist_id = prefixlist_resp2.cgx_content.get('id')
    prefixlist_name = prefixlist_resp2.cgx_content.get('name', prefixlist_id)

    # extract current_revision
    current_revision = prefixlist_resp2.cgx_content.get("_etag")

    if not prefixlist_id:
        throw_error("Unable to determine Routing Prefixlist attributes ({0})..".format(prefixlist_name),
                    prefixlist_resp2)

    output_message("   Updated Routing Prefixlist {0} (Etag {1} -> {2}).".format(prefixlist_name,
                                                                                      prev_revision,
                                                                                      current_revision))

    # update caches
    prefixlist_n2id[prefixlist_name] = prefixlist_id

    return prefixlist_id


def delete_prefixlists(leftover_prefixlists, site_id, element_id, id2n=None):
    """
    Delete a list of Routing Prefixlists
    :param leftover_prefixlists: List of Routing Prefixlist IDs to delete
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for prefixlist_id in leftover_prefixlists:
        # delete all leftover prefixlists.

        output_message("   Deleting Unconfigured Routing Prefixlist {0}.".format(id2n.get(prefixlist_id,
                                                                                      prefixlist_id)))
        prefixlist_del_resp = sdk.delete.routing_prefixlists(site_id, element_id, prefixlist_id)
        if not prefixlist_del_resp.cgx_status:
            throw_error("Could not delete Routing Prefixlist {0}: ".format(id2n.get(prefixlist_id,
                                                                                         prefixlist_id)),
                        prefixlist_del_resp)
    return


def create_routemap(config_routemap, routemap_n2id, aspath_access_lists_n2id, ip_community_lists_n2id,
                    prefixlists_n2id, site_id, element_id):
    """
    Create a new RouteMap
    :param config_routemap: RouteMap config dict
    :param routemap_n2id: RouteMap Name to ID dict
    :param aspath_access_lists_n2id: AS-Path access List Name to ID dict
    :param ip_community_lists_n2id: IP Community list Name to ID dict
    :param prefixlists_n2id: Routing Prefix Lists Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Created RouteMap ID
    """
    # make a copy of routemap to modify
    routemap_template = copy.deepcopy(config_routemap)

    # replace complex routemap objects.
    route_map_entries_list = config_routemap.get('route_map_entries')
    if route_map_entries_list and isinstance(route_map_entries_list, list):

        route_map_entries_template = []
        for entry in config_routemap['route_map_entries']:
            entry_template = copy.deepcopy(entry)

            match = entry.get('match')
            if match and isinstance(match, dict):
                match_template = copy.deepcopy(match)
                # replace names with IDs
                name_lookup_in_template(match_template, 'as_path_id', aspath_access_lists_n2id)
                name_lookup_in_template(match_template, 'community_list_id', ip_community_lists_n2id)
                name_lookup_in_template(match_template, 'ip_next_hop_id', prefixlists_n2id)
                name_lookup_in_template(match_template, 'ip_prefix_list_id', prefixlists_n2id)
                entry_template['match'] = match_template

            set_key = entry.get('set')
            if set_key and isinstance(set_key, dict):
                set_template = copy.deepcopy(set_key)
                # replace names with IDs
                name_lookup_in_template(set_template, 'ip_next_hop_id', prefixlists_n2id)
                entry_template['set'] = set_template

            # Append to template
            route_map_entries_template.append(entry_template)

        # replace original route map entries with template
        routemap_template['route_map_entries'] = route_map_entries_template

    local_debug("routemap TEMPLATE: " + str(json.dumps(routemap_template, indent=4)))

    # create routemap
    routemap_resp = sdk.post.routing_routemaps(site_id, element_id, routemap_template)

    if not routemap_resp.cgx_status:
        throw_error("Route Map creation failed: ", routemap_resp)

    routemap_id = routemap_resp.cgx_content.get('id')
    routemap_name = routemap_resp.cgx_content.get('name', routemap_id)

    if not routemap_id:
        throw_error("Unable to determine Route Map ({0})..".format(routemap_name), routemap_resp)

    output_message("   Created Route Map {0}.".format(routemap_name))

    # update caches
    routemap_n2id[routemap_name] = routemap_id

    return routemap_id


def modify_routemap(config_routemap, routemap_id, routemap_n2id, aspath_access_lists_n2id, ip_community_lists_n2id,
                    prefixlists_n2id, site_id, element_id):
    """
    Modify an existing RouteMap
    :param config_routemap: RouteMap configuration dict
    :param routemap_id: Existing RouteMap ID
    :param routemap_n2id: RouteMap Name to ID dict
    :param aspath_access_lists_n2id: AS-Path access List Name to ID dict
    :param ip_community_lists_n2id: IP Community list Name to ID dict
    :param prefixlists_n2id: Routing Prefix Lists Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Returned RouteMap ID
    """
    routemap_config = {}
    # make a copy of routemap to modify
    routemap_template = copy.deepcopy(config_routemap)

    # replace complex routemap objects.
    route_map_entries_list = config_routemap.get('route_map_entries')
    if route_map_entries_list and isinstance(route_map_entries_list, list):

        route_map_entries_template = []
        for entry in config_routemap['route_map_entries']:
            entry_template = copy.deepcopy(entry)

            match = entry.get('match')
            if match and isinstance(match, dict):
                match_template = copy.deepcopy(match)
                # replace names with IDs
                name_lookup_in_template(match_template, 'as_path_id', aspath_access_lists_n2id)
                name_lookup_in_template(match_template, 'community_list_id', ip_community_lists_n2id)
                name_lookup_in_template(match_template, 'ip_next_hop_id', prefixlists_n2id)
                name_lookup_in_template(match_template, 'ip_prefix_list_id', prefixlists_n2id)
                entry_template['match'] = match_template

            set_key = entry.get('set')
            if set_key and isinstance(set_key, dict):
                set_template = copy.deepcopy(set_key)
                # replace names with IDs
                name_lookup_in_template(set_template, 'ip_next_hop_id', prefixlists_n2id)
                entry_template['set'] = set_template

            # Append to template
            route_map_entries_template.append(entry_template)

        # replace original route map entries with template
        routemap_template['route_map_entries'] = route_map_entries_template

    local_debug("routemap TEMPLATE: " + str(json.dumps(routemap_template, indent=4)))

    # get current routemap
    routemap_resp = sdk.get.routing_routemaps(site_id, element_id, routemap_id)
    if routemap_resp.cgx_status:
        routemap_config = routemap_resp.cgx_content
    else:
        throw_error("Unable to retrieve Route Map: ", routemap_resp)

    # extract prev_revision
    prev_revision = routemap_config.get("_etag")

    # Check for changes:
    routemap_change_check = copy.deepcopy(routemap_config)
    routemap_config.update(routemap_template)
    if not force_update and routemap_config == routemap_change_check:
        # no change in config, pass.
        routemap_id = routemap_change_check.get('id')
        routemap_name = routemap_change_check.get('name')
        output_message("   No Change for Route Map {0}.".format(routemap_name))
        return routemap_id

    if debuglevel >= 3:
        local_debug("routemap DIFF: {0}".format(find_diff(routemap_change_check, routemap_config)))

    # Update routemap.
    routemap_resp2 = sdk.put.routing_routemaps(site_id, element_id, routemap_id, routemap_config)

    if not routemap_resp2.cgx_status:
        throw_error("Route Map failed: ", routemap_resp2)

    routemap_id = routemap_resp2.cgx_content.get('id')
    routemap_name = routemap_resp2.cgx_content.get('name', routemap_id)

    # extract current_revision
    current_revision = routemap_resp2.cgx_content.get("_etag")

    if not routemap_id:
        throw_error("Unable to determine Route Map attributes ({0})..".format(routemap_name), routemap_resp2)

    output_message("   Updated Route Map {0} (Etag {1} -> {2}).".format(routemap_name,
                                                                        prev_revision,
                                                                        current_revision))

    # update caches
    routemap_n2id[routemap_name] = routemap_id

    return routemap_id


def delete_routemaps(leftover_routemaps, site_id, element_id, id2n=None):
    """
    Delete a list of RouteMaps
    :param leftover_routemaps: List of RouteMap IDs
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for routemap_id in leftover_routemaps:
        # delete all leftover routemaps.

        output_message("   Deleting Unconfigured Route Map {0}.".format(id2n.get(routemap_id, routemap_id)))
        routemap_del_resp = sdk.delete.routing_routemaps(site_id, element_id, routemap_id)
        if not routemap_del_resp.cgx_status:
            throw_error("Could not delete Route Map {0}: ".format(id2n.get(routemap_id, routemap_id)),
                        routemap_del_resp)
    return


def modify_bgp_global(config_routing_bgp_global, site_id, element_id):
    """
    Modify BGP Global config - no create or destroy for bgpconfigs
    :param config_routing_bgp_global: BGP Global Config dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Returned BGP Global ID
    """
    bgp_global_config = {}
    # make a copy of bgp_global to modify
    bgp_global_template = copy.deepcopy(config_routing_bgp_global)

    local_debug("bgp_global TEMPLATE: " + str(json.dumps(bgp_global_template, indent=4)))

    # get current bgp_global
    bgp_global_resp = sdk.get.bgpconfigs(site_id, element_id)
    if bgp_global_resp.cgx_status:
        bgp_global_configs, _ = extract_items(bgp_global_resp, 'bgpconfigs')

        # sanity check, should only be one config.
        if len(bgp_global_configs) != 1:
            throw_error("BGP Global Configuration (bgpconfigs) API Reported more than 1 config: ", bgp_global_resp)

        # get first (one and only) config.
        bgp_global_config = bgp_global_configs[0]
    else:
        throw_error("Unable to retrieve bgp_global config: ", bgp_global_resp)

    # extract prev_revision
    prev_revision = bgp_global_config.get("_etag")
    # extract bgp_global id
    bgp_global_id = bgp_global_config.get('id')

    # Check for changes:
    bgp_global_change_check = copy.deepcopy(bgp_global_config)
    bgp_global_config.update(bgp_global_template)
    if not force_update and bgp_global_config == bgp_global_change_check:
        # no change in config, pass.
        bgp_global_id = bgp_global_change_check.get('id')
        output_message("   No Change for BGP Global Config {0}.".format(bgp_global_id))
        return bgp_global_id

    if debuglevel >= 3:
        local_debug("bgp_global DIFF: {0}".format(find_diff(bgp_global_change_check, bgp_global_config)))

    # Update bgp_global.
    bgp_global_resp2 = sdk.put.bgpconfigs(site_id, element_id, bgp_global_id, bgp_global_config)

    if not bgp_global_resp2.cgx_status:
        throw_error("bgp_global update failed: ", bgp_global_resp2)

    bgp_global_id = bgp_global_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = bgp_global_resp2.cgx_content.get("_etag")

    if not bgp_global_id:
        throw_error("Unable to determine bgp_global attributes (ID {0})..".format(bgp_global_id))

    output_message("   Updated BGP Global Config {0} (Etag {1} -> {2}).".format(bgp_global_id, prev_revision,
                                                                                current_revision))

    return bgp_global_id


def create_bgp_peer(config_bgp_peer, bgp_peer_n2id, routemaps_n2id, site_id, element_id):
    """
    Create a BGP Peer
    :param config_bgp_peer: BGP Peer config dict
    :param bgp_peer_n2id: BGP Peer Name to ID dict
    :param routemaps_n2id: RouteMap Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Created BGP Peer ID
    """
    # make a copy of bgp_peer to modify
    bgp_peer_template = copy.deepcopy(config_bgp_peer)

    # Get peer type
    bgp_peer_type = config_bgp_peer.get('peer_type')
    local_debug("BGP PEER TYPE: {0}".format(bgp_peer_type))

    # if Core or Edge peer, set route_maps to None for creation. Route maps get auto-created.
    if bgp_peer_type in ['core', 'edge']:
        local_debug('CORE-EDGE PEER FOUND: {0}'.format(bgp_peer_type))
        bgp_peer_template['route_map_in_id'] = None
        bgp_peer_template['route_map_out_id'] = None
    else:
        # replace flat names
        name_lookup_in_template(bgp_peer_template, 'route_map_in_id', routemaps_n2id)
        name_lookup_in_template(bgp_peer_template, 'route_map_out_id', routemaps_n2id)

    local_debug("bgp_peer TEMPLATE: " + str(json.dumps(bgp_peer_template, indent=4)))

    # create bgp_peer
    bgp_peer_resp = sdk.post.bgppeers(site_id, element_id, bgp_peer_template)

    if not bgp_peer_resp.cgx_status:
        throw_error("BGP Peer creation failed: ", bgp_peer_resp)

    bgp_peer_id = bgp_peer_resp.cgx_content.get('id')
    bgp_peer_name = bgp_peer_resp.cgx_content.get('name', bgp_peer_id)

    if not bgp_peer_id:
        throw_error("Unable to determine BGP Peer ({0})..".format(bgp_peer_name), bgp_peer_resp)

    output_message("   Created BGP Peer {0}.".format(bgp_peer_name))

    # update caches
    bgp_peer_n2id[bgp_peer_name] = bgp_peer_id

    return bgp_peer_id


def modify_bgp_peer(config_bgp_peer, bgp_peer_id, bgp_peer_n2id, routemaps_n2id, site_id, element_id):
    """
    Modify Existing BGP Peer
    :param config_bgp_peer: BGP Peer config dict
    :param bgp_peer_id: Existing BGP Peer ID
    :param bgp_peer_n2id: BGP Peer Name to ID dict
    :param routemaps_n2id: RouteMap Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Returned BGP Peer ID
    """
    bgp_peer_config = {}
    # make a copy of bgp_peer to modify
    bgp_peer_template = copy.deepcopy(config_bgp_peer)

    # replace flat names
    name_lookup_in_template(bgp_peer_template, 'route_map_in_id', routemaps_n2id)
    name_lookup_in_template(bgp_peer_template, 'route_map_out_id', routemaps_n2id)

    local_debug("bgp_peer TEMPLATE: " + str(json.dumps(bgp_peer_template, indent=4)))

    # get current bgp_peer
    bgp_peer_resp = sdk.get.bgppeers(site_id, element_id, bgp_peer_id)
    if bgp_peer_resp.cgx_status:
        bgp_peer_config = bgp_peer_resp.cgx_content
    else:
        throw_error("Unable to retrieve BGP Peer: ", bgp_peer_resp)

    # extract prev_revision
    prev_revision = bgp_peer_config.get("_etag")

    # Check for changes:
    bgp_peer_change_check = copy.deepcopy(bgp_peer_config)
    bgp_peer_config.update(bgp_peer_template)
    if not force_update and bgp_peer_config == bgp_peer_change_check:
        # no change in config, pass.
        bgp_peer_id = bgp_peer_change_check.get('id')
        bgp_peer_name = bgp_peer_change_check.get('name')
        output_message("   No Change for BGP Peer {0}.".format(bgp_peer_name))
        return bgp_peer_id

    if debuglevel >= 3:
        local_debug("bgp_peer DIFF: {0}".format(find_diff(bgp_peer_change_check, bgp_peer_config)))

    # Update bgp_peer.
    bgp_peer_resp2 = sdk.put.bgppeers(site_id, element_id, bgp_peer_id, bgp_peer_config)

    if not bgp_peer_resp2.cgx_status:
        throw_error("BGP Peer failed: ", bgp_peer_resp2)

    bgp_peer_id = bgp_peer_resp2.cgx_content.get('id')
    bgp_peer_name = bgp_peer_resp2.cgx_content.get('name', bgp_peer_id)

    # extract current_revision
    current_revision = bgp_peer_resp2.cgx_content.get("_etag")

    if not bgp_peer_id:
        throw_error("Unable to determine BGP Peer attributes ({0})..".format(bgp_peer_name), bgp_peer_resp2)

    output_message("   Updated BGP Peer {0} (Etag {1} -> {2}).".format(bgp_peer_name,
                                                                       prev_revision,
                                                                       current_revision))

    # update caches
    bgp_peer_n2id[bgp_peer_name] = bgp_peer_id

    return bgp_peer_id


def delete_bgp_peers(leftover_bgp_peers, site_id, element_id, id2n=None):
    """
    Delete a list of BGP Peers
    :param leftover_bgp_peers: List of BGP Peer IDs
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for bgp_peer_id in leftover_bgp_peers:
        # delete all leftover bgp_peers.

        output_message("   Deleting Unconfigured BGP Peer {0}.".format(id2n.get(bgp_peer_id, bgp_peer_id)))
        bgp_peer_del_resp = sdk.delete.bgppeers(site_id, element_id, bgp_peer_id)
        if not bgp_peer_del_resp.cgx_status:
            throw_error("Could not delete BGP Peer {0}: ".format(id2n.get(bgp_peer_id, bgp_peer_id)),
                        bgp_peer_del_resp)
    return


def modify_toolkit(config_toolkit, site_id, element_id):
    """
    Modify Device Toolkit (elementaccessconfigs). No Create or delete needed, always exists.
    :param config_toolkit: Toolkit Config dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Returned Toolkit ID
    """
    toolkit_config = {}
    # make a copy of toolkit to modify
    toolkit_template = copy.deepcopy(config_toolkit)

    local_debug("TOOLKIT TEMPLATE: " + str(json.dumps(toolkit_template, indent=4)))

    # get current toolkit
    toolkit_resp = sdk.get.elementaccessconfigs(element_id)
    if toolkit_resp.cgx_status:
        toolkit_config = toolkit_resp.cgx_content
    else:
        throw_error("Unable to retrieve toolkit config: ", toolkit_resp)

    # extract prev_revision
    prev_revision = toolkit_config.get("_etag")
    # extract elementaccess id
    toolkit_id = toolkit_config.get('id')

    # Check for changes:
    toolkit_change_check = copy.deepcopy(toolkit_config)
    toolkit_config.update(toolkit_template)
    if not force_update and toolkit_config == toolkit_change_check:
        # no change in config, pass.
        toolkit_id = toolkit_change_check.get('id')
        output_message("   No Change for Toolkit {0}.".format(toolkit_id))
        return toolkit_id

    if debuglevel >= 3:
        local_debug("TOOLKIT DIFF: {0}".format(find_diff(toolkit_change_check, toolkit_config)))

    # Update Toolkit.
    toolkit_resp2 = sdk.put.elementaccessconfigs(element_id, toolkit_id, toolkit_config)

    if not toolkit_resp2.cgx_status:
        throw_error("Toolkit update failed: ", toolkit_resp2)

    toolkit_id = toolkit_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = toolkit_resp2.cgx_content.get("_etag")

    if not toolkit_id:
        throw_error("Unable to determine toolkit attributes (ID {0})..".format(toolkit_id))

    output_message("   Updated Toolkit {0} (Etag {1} -> {2}).".format(toolkit_id, prev_revision,
                                                                      current_revision))

    return toolkit_id


def create_syslog(config_syslog, interfaces_n2id, site_id, element_id):
    """
    Create a new Syslog
    :param config_syslog: Syslog config dict
    :param interfaces_n2id: Interfaces Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Created Syslog ID
    """
    # make a copy of syslog to modify
    syslog_template = copy.deepcopy(config_syslog)

    # replace flat names
    name_lookup_in_template(syslog_template, 'source_interface', interfaces_n2id)

    local_debug("SYSLOG TEMPLATE: " + str(json.dumps(syslog_template, indent=4)))

    # create syslog
    syslog_resp = sdk.post.syslogservers(site_id, element_id, syslog_template)

    if not syslog_resp.cgx_status:
        throw_error("Syslog creation failed: ", syslog_resp)

    syslog_id = syslog_resp.cgx_content.get('id')
    syslog_name = syslog_resp.cgx_content.get('name', syslog_id)

    if not syslog_id:
        throw_error("Unable to determine syslog attributes (ID {0})..".format(syslog_id))

    output_message("   Created syslog {0}.".format(syslog_name))

    return syslog_id


def modify_syslog(config_syslog, syslog_id, interfaces_n2id,
                  site_id, element_id):
    """
    Modify an existing Syslog
    :param config_syslog: Syslog config dict
    :param syslog_id: Existing syslog ID
    :param interfaces_n2id: Interfaces Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Returned Syslog ID
    """
    syslog_config = {}
    # make a copy of syslog to modify
    syslog_template = copy.deepcopy(config_syslog)

    # replace flat names
    name_lookup_in_template(syslog_template, 'source_interface', interfaces_n2id)

    local_debug("SYSLOG TEMPLATE: " + str(json.dumps(syslog_template, indent=4)))

    # get current syslog
    syslog_resp = sdk.get.syslogservers(site_id, element_id, syslog_id)
    if syslog_resp.cgx_status:
        syslog_config = syslog_resp.cgx_content
    else:
        throw_error("Unable to retrieve syslog: ", syslog_resp)

    # extract prev_revision
    prev_revision = syslog_config.get("_etag")

    # Check for changes:
    syslog_change_check = copy.deepcopy(syslog_config)
    syslog_config.update(syslog_template)
    if not force_update and syslog_config == syslog_change_check:
        # no change in config, pass.
        syslog_id = syslog_change_check.get('id')
        syslog_name = syslog_change_check.get('name')
        output_message("   No Change for Syslog {0}.".format(syslog_name))
        return syslog_id

    if debuglevel >= 3:
        local_debug("SYSLOG DIFF: {0}".format(find_diff(syslog_change_check, syslog_config)))

    # Update Syslog.
    syslog_resp2 = sdk.put.syslogservers(site_id, element_id, syslog_id, syslog_config)

    if not syslog_resp2.cgx_status:
        throw_error("Syslog update failed: ", syslog_resp2)

    syslog_id = syslog_resp.cgx_content.get('id')
    syslog_name = syslog_resp.cgx_content.get('name', syslog_id)

    # extract current_revision
    current_revision = syslog_resp2.cgx_content.get("_etag")

    if not syslog_id:
        throw_error("Unable to determine syslog attributes (ID {0})..".format(syslog_id))

    output_message("   Updated Syslog {0} (Etag {1} -> {2}).".format(syslog_name, prev_revision,
                                                                     current_revision))

    return syslog_id


def delete_syslogs(leftover_syslogs, site_id, element_id, id2n=None):
    """
    Delete a list of Syslogs
    :param leftover_syslogs: List of Syslog IDs
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for syslog_id in leftover_syslogs:
        # delete all leftover syslogs.

        output_message("   Deleting Unconfigured Syslog {0}.".format(id2n.get(syslog_id, syslog_id)))
        syslog_del_resp = sdk.delete.syslogservers(site_id, element_id, syslog_id)
        if not syslog_del_resp.cgx_status:
            throw_error("Could not delete Syslog {0}: ".format(id2n.get(syslog_id, syslog_id)),
                        syslog_del_resp)
    return


def create_ntp(config_ntp, interfaces_n2id, site_id, element_id):
    """
    Create an NTP config
    :param config_ntp: NTP config dict
    :param interfaces_n2id: Interfaces Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Created NTP ID
    """
    # make a copy of ntp to modify
    ntp_template = copy.deepcopy(config_ntp)

    local_debug("NTP TEMPLATE: " + str(json.dumps(ntp_template, indent=4)))

    # create ntp
    ntp_resp = sdk.post.ntp(element_id, ntp_template)

    if not ntp_resp.cgx_status:
        throw_error("Ntp creation failed: ", ntp_resp)

    ntp_id = ntp_resp.cgx_content.get('id')
    ntp_name = ntp_resp.cgx_content.get('name', ntp_id)

    if not ntp_id:
        throw_error("Unable to determine ntp attributes (ID {0})..".format(ntp_id))

    output_message("   Created ntp {0}.".format(ntp_name))

    return ntp_id


def modify_ntp(config_ntp, ntp_id, interfaces_n2id,
               site_id, element_id):
    """
    Modify an existing NTP config
    :param config_ntp: NTP config dict
    :param ntp_id: Existing NTP ID
    :param interfaces_n2id: Interfaces Name to ID
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Returned NTP ID
    """
    ntp_config = {}
    # make a copy of ntp to modify
    ntp_template = copy.deepcopy(config_ntp)

    # replace flat names
    name_lookup_in_template(ntp_template, 'source_interface', interfaces_n2id)

    local_debug("NTP TEMPLATE: " + str(json.dumps(ntp_template, indent=4)))

    # get current ntp
    ntp_resp = sdk.get.ntp(element_id, ntp_id)
    if ntp_resp.cgx_status:
        ntp_config = ntp_resp.cgx_content
    else:
        throw_error("Unable to retrieve ntp: ", ntp_resp)

    # extract prev_revision
    prev_revision = ntp_config.get("_etag")

    # Check for changes:
    ntp_change_check = copy.deepcopy(ntp_config)
    ntp_config.update(ntp_template)
    if not force_update and ntp_config == ntp_change_check:
        # no change in config, pass.
        ntp_id = ntp_change_check.get('id')
        ntp_name = ntp_change_check.get('name')
        output_message("   No Change for Ntp {0}.".format(ntp_name))
        return ntp_id

    if debuglevel >= 3:
        local_debug("NTP DIFF: {0}".format(find_diff(ntp_change_check, ntp_config)))

    # Update Ntp.
    ntp_resp2 = sdk.put.ntp(element_id, ntp_id, ntp_config)

    if not ntp_resp2.cgx_status:
        throw_error("Ntp update failed: ", ntp_resp2)

    ntp_id = ntp_resp.cgx_content.get('id')
    ntp_name = ntp_resp.cgx_content.get('name', ntp_id)

    # extract current_revision
    current_revision = ntp_resp2.cgx_content.get("_etag")

    if not ntp_id:
        throw_error("Unable to determine ntp attributes (ID {0})..".format(ntp_id))

    output_message("   Updated Ntp {0} (Etag {1} -> {2}).".format(ntp_name, prev_revision,
                                                                  current_revision))

    return ntp_id


def delete_ntps(leftover_ntps, site_id, element_id, id2n=None):
    """
    Delete a list of NTP configs
    :param leftover_ntps: List of NTP IDs
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for ntp_id in leftover_ntps:
        # delete all leftover ntps.

        output_message("   Deleting Unconfigured Ntp {0}.".format(id2n.get(ntp_id, ntp_id)))
        ntp_del_resp = sdk.delete.ntp(element_id, ntp_id)
        if not ntp_del_resp.cgx_status:
            throw_error("Could not delete Ntp {0}: ".format(id2n.get(ntp_id, ntp_id)),
                        ntp_del_resp)
    return


def create_snmp_agent(config_snmp_agent, interfaces_n2id, site_id, element_id):
    """
    Create SNMP Agent configs
    :param config_snmp_agent: SNMP Agent config dict
    :param interfaces_n2id: Interfaces Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Created SNMP Agent ID
    """
    # make a copy of snmp_agent to modify
    snmp_agent_template = copy.deepcopy(config_snmp_agent)

    local_debug("SNMP_AGENT TEMPLATE: " + str(json.dumps(snmp_agent_template, indent=4)))

    # create snmp_agent
    snmp_agent_resp = sdk.post.snmpagents(site_id, element_id, snmp_agent_template)

    if not snmp_agent_resp.cgx_status:
        throw_error("Snmp_agent creation failed: ", snmp_agent_resp)

    snmp_agent_id = snmp_agent_resp.cgx_content.get('id')

    if not snmp_agent_id:
        throw_error("Unable to determine snmp_agent attributes (ID {0})..".format(snmp_agent_id))

    output_message("   Created Snmp agent {0}.".format(snmp_agent_id))

    return snmp_agent_id


def modify_snmp_agent(config_snmp_agent, snmp_agent_id, interfaces_n2id,
                  site_id, element_id):
    """
    Modify Existing SNMP Agent config
    :param config_snmp_agent: SNMP Agent config dict
    :param snmp_agent_id: Existing SNMP Agent ID
    :param interfaces_n2id: Interfaces Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Returned SNMP Agent ID
    """
    snmp_agent_config = {}
    # make a copy of snmp_agent to modify
    snmp_agent_template = copy.deepcopy(config_snmp_agent)

    local_debug("SNMP_AGENT TEMPLATE: " + str(json.dumps(snmp_agent_template, indent=4)))

    # get current snmp_agent
    snmp_agent_resp = sdk.get.snmpagents(site_id, element_id, snmp_agent_id)
    if snmp_agent_resp.cgx_status:
        snmp_agent_config = snmp_agent_resp.cgx_content
    else:
        throw_error("Unable to retrieve snmp_agent: ", snmp_agent_resp)

    # extract prev_revision
    prev_revision = snmp_agent_config.get("_etag")

    # Check for changes:
    snmp_agent_change_check = copy.deepcopy(snmp_agent_config)
    snmp_agent_config.update(snmp_agent_template)
    if not force_update and snmp_agent_config == snmp_agent_change_check:
        # no change in config, pass.
        snmp_agent_id = snmp_agent_change_check.get('id')
        output_message("   No Change for Snmp_agent {0}.".format(snmp_agent_id))
        return snmp_agent_id

    if debuglevel >= 3:
        local_debug("SNMP_AGENT DIFF: {0}".format(find_diff(snmp_agent_change_check, snmp_agent_config)))

    # Update Snmp_agent.
    snmp_agent_resp2 = sdk.put.snmpagents(site_id, element_id, snmp_agent_id, snmp_agent_config)

    if not snmp_agent_resp2.cgx_status:
        throw_error("Snmp_agent update failed: ", snmp_agent_resp2)

    snmp_agent_id = snmp_agent_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = snmp_agent_resp2.cgx_content.get("_etag")

    if not snmp_agent_id:
        throw_error("Unable to determine snmp_agent attributes (ID {0})..".format(snmp_agent_id))

    output_message("   Updated Snmp agent {0} (Etag {1} -> {2}).".format(snmp_agent_id, prev_revision,
                                                                         current_revision))

    return snmp_agent_id


def delete_snmp_agents(leftover_snmp_agents, site_id, element_id, id2n=None):
    """
    Delete a list of SNMP Agents
    :param leftover_snmp_agents: List of SNMP Agent IDs
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for snmp_agent_id in leftover_snmp_agents:
        # delete all leftover snmp_agents.

        output_message("   Deleting Unconfigured Snmp agent {0}.".format(id2n.get(snmp_agent_id, snmp_agent_id)))
        snmp_agent_del_resp = sdk.delete.snmpagents(site_id, element_id, snmp_agent_id)
        if not snmp_agent_del_resp.cgx_status:
            throw_error("Could not delete Snmp_agent {0}: ".format(id2n.get(snmp_agent_id, snmp_agent_id)),
                        snmp_agent_del_resp)
    return


def create_snmp_trap(config_snmp_trap, interfaces_n2id, site_id, element_id):
    """
    Create SNMP Trap
    :param config_snmp_trap: SNMP Trap config dict
    :param interfaces_n2id: Interfaces Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Created SNMP Trap ID
    """
    # make a copy of snmp_trap to modify
    snmp_trap_template = copy.deepcopy(config_snmp_trap)

    # replace flat names
    name_lookup_in_template(snmp_trap_template, 'source_interface', interfaces_n2id)

    local_debug("SNMP_TRAP TEMPLATE: " + str(json.dumps(snmp_trap_template, indent=4)))

    # create snmp_trap
    snmp_trap_resp = sdk.post.snmptraps(site_id, element_id, snmp_trap_template)

    if not snmp_trap_resp.cgx_status:
        throw_error("Snmp_trap creation failed: ", snmp_trap_resp)

    snmp_trap_id = snmp_trap_resp.cgx_content.get('id')

    if not snmp_trap_id:
        throw_error("Unable to determine snmp_trap attributes (ID {0})..".format(snmp_trap_id))

    output_message("   Created Snmp trap {0}.".format(snmp_trap_id))

    return snmp_trap_id


def modify_snmp_trap(config_snmp_trap, snmp_trap_id, interfaces_n2id,
                     site_id, element_id):
    """
    Modify Existing SNMP Trap
    :param config_snmp_trap: SNMP Trap config dict
    :param snmp_trap_id: Existing SNMP Trap ID
    :param interfaces_n2id: Interfaces Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Returned SNMP Trap ID
    """
    snmp_trap_config = {}
    # make a copy of snmp_trap to modify
    snmp_trap_template = copy.deepcopy(config_snmp_trap)

    # replace flat names
    name_lookup_in_template(snmp_trap_template, 'source_interface', interfaces_n2id)

    local_debug("SNMP_TRAP TEMPLATE: " + str(json.dumps(snmp_trap_template, indent=4)))

    # get current snmp_trap
    snmp_trap_resp = sdk.get.snmptraps(site_id, element_id, snmp_trap_id)
    if snmp_trap_resp.cgx_status:
        snmp_trap_config = snmp_trap_resp.cgx_content
    else:
        throw_error("Unable to retrieve snmp_trap: ", snmp_trap_resp)

    # extract prev_revision
    prev_revision = snmp_trap_config.get("_etag")

    # Check for changes:
    snmp_trap_change_check = copy.deepcopy(snmp_trap_config)
    snmp_trap_config.update(snmp_trap_template)
    if not force_update and snmp_trap_config == snmp_trap_change_check:
        # no change in config, pass.
        snmp_trap_id = snmp_trap_change_check.get('id')
        output_message("   No Change for Snmp_trap {0}.".format(snmp_trap_id))
        return snmp_trap_id

    if debuglevel >= 3:
        local_debug("SNMP_TRAP DIFF: {0}".format(find_diff(snmp_trap_change_check, snmp_trap_config)))

    # Update Snmp_trap.
    snmp_trap_resp2 = sdk.put.snmptraps(site_id, element_id, snmp_trap_id, snmp_trap_config)

    if not snmp_trap_resp2.cgx_status:
        throw_error("Snmp_trap update failed: ", snmp_trap_resp2)

    snmp_trap_id = snmp_trap_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = snmp_trap_resp2.cgx_content.get("_etag")

    if not snmp_trap_id:
        throw_error("Unable to determine snmp_trap attributes (ID {0})..".format(snmp_trap_id))

    output_message("   Updated Snmp trap {0} (Etag {1} -> {2}).".format(snmp_trap_id, prev_revision,
                                                                        current_revision))

    return snmp_trap_id


def delete_snmp_traps(leftover_snmp_traps, site_id, element_id, id2n=None):
    """
    Delete a list of SNMP Traps
    :param leftover_snmp_traps: List of SNMP Trap IDs
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for snmp_trap_id in leftover_snmp_traps:
        # delete all leftover snmp_traps.

        output_message("   Deleting Unconfigured Snmp trap {0}.".format(id2n.get(snmp_trap_id, snmp_trap_id)))
        snmp_trap_del_resp = sdk.delete.snmptraps(site_id, element_id, snmp_trap_id)
        if not snmp_trap_del_resp.cgx_status:
            throw_error("Could not delete Snmp_trap {0}: ".format(id2n.get(snmp_trap_id, snmp_trap_id)),
                        snmp_trap_del_resp)
    return


def create_element_extension(config_element_extension, element_extensions_n2id, waninterfaces_n2id, lannetworks_n2id,
                             interfaces_n2id, site_id, element_id):
    """
    Create a new Element Extension
    :param config_element_extension: Element Extension config dict
    :param element_extensions_n2id: Element Extension Name to ID dict
    :param waninterfaces_n2id: WAN Interface Name to ID dict
    :param lannetworks_n2id: LAN Networks Name to ID dict
    :param interfaces_n2id: Interfaces Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Created Element Extension ID
    """
    # make a copy of element_extension to modify
    element_extension_template = copy.deepcopy(config_element_extension)

    # Entity ID can be a multitude of things. Try them all.
    name_lookup_in_template(element_extension_template, 'entity_id', interfaces_n2id)
    name_lookup_in_template(element_extension_template, 'entity_id', waninterfaces_n2id)
    name_lookup_in_template(element_extension_template, 'entity_id', lannetworks_n2id)
    # look up appdefs last, as appdef id 0 = unknown, and may match other 0's
    name_lookup_in_template(element_extension_template, 'entity_id', appdefs_n2id)

    local_debug("ELEMENT_EXTENSION TEMPLATE: " + str(json.dumps(element_extension_template, indent=4)))

    # create element_extension
    element_extension_resp = sdk.post.element_extensions(site_id, element_id, element_extension_template)

    if not element_extension_resp.cgx_status:
        throw_error("Element_extension creation failed: ", element_extension_resp)

    element_extension_name = element_extension_resp.cgx_content.get('name')
    element_extension_id = element_extension_resp.cgx_content.get('id')

    if not element_extension_name or not element_extension_id:
        throw_error("Unable to determine element_extension attributes (Name: {0}, ID {1}).."
                    "".format(element_extension_name, element_extension_id))

    output_message("   Created element extension {0}.".format(element_extension_name))

    # update caches
    element_extensions_n2id[element_extension_name] = element_extension_id

    return element_extension_id


def modify_element_extension(config_element_extension, element_extension_id, element_extensions_n2id,
                             waninterfaces_n2id, lannetworks_n2id, interfaces_n2id, site_id, element_id):
    """
    Modify existing Element Extension
    :param config_element_extension: Element Extension config dict
    :param element_extension_id: Existing Element Extension ID
    :param element_extensions_n2id: Element Extension Name to ID dict
    :param waninterfaces_n2id: WAN Interface Name to ID dict
    :param lannetworks_n2id: LAN Networks Name to ID dict
    :param interfaces_n2id: Interfaces Name to ID dict
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :return: Returned Element Extension ID
    """
    element_extension_config = {}
    # make a copy of element_extension to modify
    element_extension_template = copy.deepcopy(config_element_extension)

    # Entity ID can be a multitude of things. Try them all.
    name_lookup_in_template(element_extension_template, 'entity_id', interfaces_n2id)
    name_lookup_in_template(element_extension_template, 'entity_id', waninterfaces_n2id)
    name_lookup_in_template(element_extension_template, 'entity_id', lannetworks_n2id)
    # look up appdefs last, as appdef id 0 = unknown, and may match other 0's
    name_lookup_in_template(element_extension_template, 'entity_id', appdefs_n2id)

    local_debug("ELEMENT_EXTENSION TEMPLATE: " + str(json.dumps(element_extension_template, indent=4)))

    # get current element_extension
    element_extension_resp = sdk.get.element_extensions(site_id, element_id, element_extension_id)
    if element_extension_resp.cgx_status:
        element_extension_config = element_extension_resp.cgx_content
    else:
        throw_error("Unable to retrieve element_extension: ", element_extension_resp)

    # extract prev_revision
    prev_revision = element_extension_config.get("_etag")

    # Check for changes:
    element_extension_change_check = copy.deepcopy(element_extension_config)
    element_extension_config.update(element_extension_template)
    if not force_update and element_extension_config == element_extension_change_check:
        # no change in config, pass.
        element_extension_id = element_extension_change_check.get('id')
        element_extension_name = element_extension_change_check.get('name')
        output_message("   No Change for Element_extension {0}.".format(element_extension_name))
        return element_extension_id

    if debuglevel >= 3:
        local_debug("ELEMENT_EXTENSION DIFF: {0}".format(find_diff(element_extension_change_check,
                                                                   element_extension_config)))

    # Update Element_extension.
    element_extension_resp2 = sdk.put.element_extensions(site_id, element_id, element_extension_id,
                                                         element_extension_config)

    if not element_extension_resp2.cgx_status:
        throw_error("Element_extension update failed: ", element_extension_resp2)

    element_extension_name = element_extension_resp2.cgx_content.get('name')
    element_extension_id = element_extension_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = element_extension_resp2.cgx_content.get("_etag")

    if not element_extension_name or not element_extension_id:
        throw_error("Unable to determine element_extension attributes (Name: {0}, ID {1}).."
                    "".format(element_extension_name, element_extension_id))

    output_message("   Updated Element extension {0} (Etag {1} -> {2}).".format(element_extension_name, prev_revision,
                                                                                current_revision))

    # update caches
    element_extensions_n2id[element_extension_name] = element_extension_id

    return element_extension_id


def delete_element_extensions(leftover_element_extensions, site_id, element_id, id2n=None):
    """
    Delete a list of Element Extensions
    :param leftover_element_extensions: List of Element Extension IDs
    :param site_id: Site ID to use
    :param element_id: Element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for element_extension_id in leftover_element_extensions:
        # delete all leftover element_extensions.

        output_message("   Deleting Unconfigured Element_extension {0}.".format(id2n.get(element_extension_id,
                                                                                element_extension_id)))
        element_extension_del_resp = sdk.delete.element_extensions(site_id, element_id, element_extension_id)
        if not element_extension_del_resp.cgx_status:
            throw_error("Could not delete Element_extension {0}: ".format(id2n.get(element_extension_id,
                                                                                   element_extension_id)),
                        element_extension_del_resp)
    return


def create_element_securityzone(config_element_securityzone, waninterface_n2id, lannetworks_n2id, interfaces_n2id,
                                site_id, element_id):
    """
    Create a element Security Zone Mapping
    :param config_element_securityzone: element Securityzone config dict
    :param waninterface_n2id: element WAN InterfaceName to ID map (site specific)
    :param lannetworks_n2id: LAN Networks Name to ID map (site specific)
    :param interfaces_n2id: Interfaces Name to ID map (site and element specific)
    :param site_id: site ID to use
    :param element_id: element ID to use
    :return: element Securityzone

    """
    # make a copy of site_securityzone to modify
    element_securityzone_template = copy.deepcopy(config_element_securityzone)

    # perform name -> ID lookups
    name_lookup_in_template(element_securityzone_template, 'zone_id', securityzones_n2id)

    # replace complex names
    esz_entry_interface_ids = config_element_securityzone.get('interface_ids')
    if esz_entry_interface_ids and isinstance(esz_entry_interface_ids, list):
        esz_entry_interface_ids_template = []
        for esz_entry_interface_id in esz_entry_interface_ids:
            esz_entry_interface_ids_template.append(interfaces_n2id.get(esz_entry_interface_id,
                                                                        esz_entry_interface_id))
        element_securityzone_template['interface_ids'] = esz_entry_interface_ids_template

    esz_entry_lannetwork_ids = config_element_securityzone.get('lannetwork_ids')
    if esz_entry_lannetwork_ids and isinstance(esz_entry_lannetwork_ids, list):
        esz_entry_lannetwork_ids_template = []
        for esz_entry_lannetwork_id in esz_entry_lannetwork_ids:
            esz_entry_lannetwork_ids_template.append(lannetworks_n2id.get(esz_entry_lannetwork_id,
                                                                          esz_entry_lannetwork_id))
        element_securityzone_template['lannetwork_ids'] = esz_entry_lannetwork_ids_template

    esz_entry_waninterface_ids = config_element_securityzone.get('waninterface_ids')
    if esz_entry_waninterface_ids and isinstance(esz_entry_waninterface_ids, list):
        esz_entry_waninterface_ids_template = []
        for esz_entry_waninterface_id in esz_entry_waninterface_ids:
            esz_entry_waninterface_ids_template.append(waninterface_n2id.get(esz_entry_waninterface_id,
                                                                             esz_entry_waninterface_id))
        element_securityzone_template['waninterface_ids'] = esz_entry_waninterface_ids_template

    esz_entry_wanoverlay_ids = config_element_securityzone.get('wanoverlay_ids')
    if esz_entry_wanoverlay_ids and isinstance(esz_entry_wanoverlay_ids, list):
        esz_entry_wanoverlay_ids_template = []
        for esz_entry_wanoverlay_id in esz_entry_wanoverlay_ids:
            esz_entry_wanoverlay_ids_template.append(wanoverlays_n2id.get(esz_entry_wanoverlay_id,
                                                                          esz_entry_wanoverlay_id))
        element_securityzone_template['wanoverlay_ids'] = esz_entry_wanoverlay_ids_template

    local_debug("ELEMENT_SECURITYZONE TEMPLATE: " + str(json.dumps(element_securityzone_template, indent=4)))

    # create element_securityzone
    element_securityzone_resp = sdk.post.elementsecurityzones(site_id, element_id, element_securityzone_template)

    if not element_securityzone_resp.cgx_status:
        throw_error("Element Securityzone creation failed: ", element_securityzone_resp)

    element_securityzone_id = element_securityzone_resp.cgx_content.get('id')
    element_securityzone_zone_id = element_securityzone_resp.cgx_content.get('zone_id')

    if not element_securityzone_id or not element_securityzone_zone_id:
        throw_error("Unable to determine element_securityzone attributes (ID {0}, Zone ID {1}).."
                    "".format(element_securityzone_id, element_securityzone_zone_id))

    # Try to get zone name this is for.
    esz_zone_name = securityzones_id2n.get(element_securityzone_zone_id, element_securityzone_zone_id)

    output_message("   Created Element Securityzone Mapping for Zone '{0}'.".format(esz_zone_name))

    return element_securityzone_id


def modify_element_securityzone(config_element_securityzone, element_securityzone_id, waninterface_n2id,
                                lannetworks_n2id, interfaces_n2id, site_id, element_id):
    """
    Modify Existing element Security Zone Mapping
    :param config_element_securityzone: element Securityzone config dict
    :param element_securityzone_id: Existing element Securityzone ID
    :param waninterface_n2id: element WAN InterfaceName to ID map (site specific)
    :param lannetworks_n2id: LAN Networks Name to ID map (site specific)
    :param interfaces_n2id: Interfaces Name to ID map (site and element specific)
    :param site_id: site ID to use
    :param element_id: element ID to use
    :return: Returned element Securityzone ID
    """
    element_securityzone_config = {}
    # make a copy of site_securityzone to modify
    element_securityzone_template = copy.deepcopy(config_element_securityzone)

    # perform name -> ID lookups
    name_lookup_in_template(element_securityzone_template, 'zone_id', securityzones_n2id)

    # replace complex names
    esz_entry_interface_ids = config_element_securityzone.get('interface_ids')
    if esz_entry_interface_ids and isinstance(esz_entry_interface_ids, list):
        esz_entry_interface_ids_template = []
        for esz_entry_interface_id in esz_entry_interface_ids:
            esz_entry_interface_ids_template.append(interfaces_n2id.get(esz_entry_interface_id,
                                                                        esz_entry_interface_id))
        element_securityzone_template['interface_ids'] = esz_entry_interface_ids_template

    esz_entry_lannetwork_ids = config_element_securityzone.get('lannetwork_ids')
    if esz_entry_lannetwork_ids and isinstance(esz_entry_lannetwork_ids, list):
        esz_entry_lannetwork_ids_template = []
        for esz_entry_lannetwork_id in esz_entry_lannetwork_ids:
            esz_entry_lannetwork_ids_template.append(lannetworks_n2id.get(esz_entry_lannetwork_id,
                                                                          esz_entry_lannetwork_id))
        element_securityzone_template['lannetwork_ids'] = esz_entry_lannetwork_ids_template

    esz_entry_waninterface_ids = config_element_securityzone.get('waninterface_ids')
    if esz_entry_waninterface_ids and isinstance(esz_entry_waninterface_ids, list):
        esz_entry_waninterface_ids_template = []
        for esz_entry_waninterface_id in esz_entry_waninterface_ids:
            esz_entry_waninterface_ids_template.append(waninterface_n2id.get(esz_entry_waninterface_id,
                                                                             esz_entry_waninterface_id))
        element_securityzone_template['waninterface_ids'] = esz_entry_waninterface_ids_template

    esz_entry_wanoverlay_ids = config_element_securityzone.get('wanoverlay_ids')
    if esz_entry_wanoverlay_ids and isinstance(esz_entry_wanoverlay_ids, list):
        esz_entry_wanoverlay_ids_template = []
        for esz_entry_wanoverlay_id in esz_entry_wanoverlay_ids:
            esz_entry_wanoverlay_ids_template.append(wanoverlays_n2id.get(esz_entry_wanoverlay_id,
                                                                          esz_entry_wanoverlay_id))
        element_securityzone_template['wanoverlay_ids'] = esz_entry_wanoverlay_ids_template

    local_debug("ELEMENT_SECURITYZONE TEMPLATE: " + str(json.dumps(element_securityzone_template, indent=4)))

    # get current element_securityzone
    element_securityzone_resp = sdk.get.elementsecurityzones(site_id, element_id, element_securityzone_id)
    if element_securityzone_resp.cgx_status:
        element_securityzone_config = element_securityzone_resp.cgx_content
    else:
        throw_error("Unable to retrieve Element Securityzone: ", element_securityzone_resp)

    # extract prev_revision
    prev_revision = element_securityzone_config.get("_etag")

    # Check for changes:
    element_securityzone_change_check = copy.deepcopy(element_securityzone_config)
    element_securityzone_config.update(element_securityzone_template)
    if not force_update and element_securityzone_config == element_securityzone_change_check:
        # no change in config, pass.
        element_securityzone_id = element_securityzone_change_check.get('id')
        element_securityzone_zone_id = element_securityzone_resp.cgx_content.get('zone_id')
        # Try to get zone name this is for.
        esz_zone_name = securityzones_id2n.get(element_securityzone_zone_id, element_securityzone_zone_id)
        output_message("   No Change for Element Securityzone mapping for {0}.".format(esz_zone_name))
        return element_securityzone_id

    if debuglevel >= 3:
        local_debug("ELEMENT_SECURITYZONE DIFF: {0}".format(find_diff(element_securityzone_change_check,
                                                                      element_securityzone_config)))

    # Update element_securityzone.
    element_securityzone_resp2 = sdk.put.elementsecurityzones(site_id, element_id, element_securityzone_id,
                                                              element_securityzone_config)

    if not element_securityzone_resp2.cgx_status:
        throw_error("Element Securityzone update failed: ", element_securityzone_resp2)

    element_securityzone_zone_id = element_securityzone_resp.cgx_content.get('zone_id')
    element_securityzone_id = element_securityzone_resp2.cgx_content.get('id')

    # extract current_revision
    current_revision = element_securityzone_resp2.cgx_content.get("_etag")

    if not element_securityzone_zone_id or not element_securityzone_id:
        throw_error("Unable to determine element securityzone attributes (ID {0}, Zone {1}).."
                    "".format(element_securityzone_id, element_securityzone_zone_id))

    # Try to get zone name this is for.
    esz_zone_name = securityzones_id2n.get(element_securityzone_zone_id, element_securityzone_zone_id)

    output_message("   Updated Element Securityzone mapping for Zone '{0}' (Etag {1} -> {2})."
                   "".format(esz_zone_name, prev_revision,current_revision))

    return element_securityzone_id


def delete_element_securityzones(leftover_element_securityzones, site_id, element_id, id2n=None):
    """
    Delete element Securityzone Mappings
    :param leftover_element_securityzones: List of element Securityzone IDs to delete
    :param site_id: site ID to use
    :param element_id: element ID to use
    :param id2n: Optional - ID to Name lookup dict
    :return: None
    """
    # ensure id2n is empty dict if not set.
    if id2n is None:
        id2n = {}

    for element_securityzone_id in leftover_element_securityzones:
        # delete all leftover element_securityzones.

        # Try to get zone name
        esz_zone_name = securityzones_id2n.get(id2n.get(element_securityzone_id, element_securityzone_id),
                                               element_securityzone_id)

        output_message("   Deleting Unconfigured Element Securityzone mapping for Zone '{0}'."
                       "".format(esz_zone_name))
        element_securityzone_del_resp = sdk.delete.elementsecurityzones(site_id, element_id, element_securityzone_id)
        if not element_securityzone_del_resp.cgx_status:
            throw_error("Could not delete Element Securityzone {0}: ".format(id2n.get(element_securityzone_id,
                                                                                      element_securityzone_id)),
                        element_securityzone_del_resp)
    return


def do_site(loaded_config, destroy, destroy_declaim, passed_sdk=None, passed_timeout_offline=None, passed_timeout_claim=None,
            passed_timeout_upgrade=None, passed_timeout_state=None, passed_wait_upgrade=None,
            passed_interval_timeout=None, passed_force_update=None):
    """
    Main Site config/deploy worker function.
    :param loaded_config: Loaded config in Python Dict format
    :param destroy: Bool, True = Create site/objects, False = Destroy (completely, use with caution).
    :param destroy-declaim: Bool, True = Destroy completely and declaim element.
    :param passed_sdk: Authenticated `cloudgenix.API()` constructor.
    :param passed_timeout_offline: Optional - Time to wait if ION is offline (seconds)
    :param passed_timeout_claim: Optional - Time to wait for ION to claim (seconds)
    :param passed_timeout_upgrade: Optional - Time to wait for ION to upgrade (seconds)
    :param passed_timeout_state: Optional - Time to wait if ION to get to correct state (seconds)
    :param passed_wait_upgrade: Optional - Bool, True = Wait for ION upgrade to finsh, False = Continue.
    :param passed_interval_timeout: Optional - Time recheck for success during timeout waits above (seconds)
    :param passed_force_update: Optional - Bool, True = Force API PUTs even if no change is detected.
    :return:
    """
    global debuglevel
    global sdk_debuglevel
    global sdk
    global timeout_offline
    global timeout_claim
    global timeout_upgrade
    global wait_upgrade
    global timeout_state
    global interval_timeout
    global force_update

    # read passed items.
    if not isinstance(destroy, bool):
        throw_error("do_site function requires 'destroy' be True or False only.")

    # read passed items.
    if not isinstance(destroy_declaim, bool):
        throw_error("do_site function requires 'destroy-declaim' be True or False only.")

    if passed_sdk is not None:
        sdk = passed_sdk
    if passed_timeout_offline is not None:
        timeout_offline = passed_timeout_offline
    if passed_timeout_claim is not None:
        timeout_claim = passed_timeout_claim
    if passed_timeout_upgrade is not None:
        timeout_upgrade = passed_timeout_upgrade
    if passed_timeout_state is not None:
        timeout_state = passed_timeout_state
    if passed_wait_upgrade is not None:
        wait_upgrade = passed_wait_upgrade
    if passed_interval_timeout is not None:
        interval_timeout = passed_interval_timeout
    if passed_force_update is not None:
        force_update = passed_force_update

    # load the root config
    config_sites = parse_root_config(loaded_config)

    # SAFETY FACTOR CHECK
    site_count = len(config_sites.keys())
    if site_count > site_safety_factor:
        throw_error("Too many sites to configure in specified YAML config:\n"
                    "\tSites in file: {0}\n"
                    "\tSites allowed by safety factor: {1}\n"
                    "If the script should be allowed to modify more sites, please increase the allowed site safety "
                    "factor by using the \"--site-safety-factor <count of max sites allowed>\" command-line argument."
                    "".format(site_count, site_safety_factor))

    # update global var cache.
    update_global_cache()

    # handle create
    if not destroy:

        # -- Start Sites - Iterate loop
        for config_site_name, config_site_value in config_sites.items():
            # recombine site object
            config_site = recombine_named_key_value(config_site_name, config_site_value, name_key='name')

            # parse site config
            config_waninterfaces, config_lannetworks, config_elements, config_dhcpservers, config_site_extensions, \
                config_site_security_zones, config_spokeclusters = parse_site_config(config_site)

            # Determine site ID.
            # look for implicit ID in object.
            implicit_site_id = config_site.get('id')
            name_site_id = sites_n2id.get(config_site_name)

            if implicit_site_id is not None:
                site_id = implicit_site_id

            elif name_site_id is not None:
                # look up ID by name on existing sites.
                site_id = name_site_id
            else:
                # no site object.
                site_id = None

            # Create or modify site.
            if site_id is not None:
                # Site exists, modify.
                site_id = modify_site(config_site, site_id)

            else:
                # Site does not exist, create.
                site_id = create_site(config_site)
            # -- End Sites

            # -- Start WAN Interfaces
            waninterfaces_resp = sdk.get.waninterfaces(site_id)
            waninterfaces_cache, leftover_waninterfaces = extract_items(waninterfaces_resp, 'waninterfaces')
            waninterfaces_n2id = build_lookup_dict(waninterfaces_cache)
            # build Circuit Category (label) and WAN Network lookup tables
            waninterfaces_l2id = build_lookup_dict(waninterfaces_cache, key_val='label_id')

            # iterate configs
            for config_waninterface_name, config_waninterface_value in config_waninterfaces.items():
                # recombine object
                config_waninterface = recombine_named_key_value(config_waninterface_name, config_waninterface_value,
                                                                name_key='name')

                # no need to get wan interface config, no child config objects.

                # Determine waninterface ID.
                # look for implicit ID in object.
                implicit_waninterface_id = config_waninterface.get('id')
                name_waninterface_id = waninterfaces_n2id.get(config_waninterface_name)

                # Ok, Waninterfaces require a unique Circuit Category Look up based on this first.
                config_waninterface_label_name = config_waninterface.get('label_id')
                config_waninterface_label_id = waninterfacelabels_n2id.get(config_waninterface_label_name,
                                                                           config_waninterface_label_name)
                label_waninterface_id = waninterfaces_l2id.get(config_waninterface_label_id)

                if implicit_waninterface_id is not None:
                    waninterface_id = implicit_waninterface_id

                elif label_waninterface_id is not None:
                    # look up ID by label first on existing waninterfaces.
                    waninterface_id = label_waninterface_id

                elif name_waninterface_id is not None:
                    # look up ID by name third on existing waninterfaces.
                    waninterface_id = name_waninterface_id
                else:
                    # no waninterface object.
                    waninterface_id = None

                # Create or modify waninterface.
                if waninterface_id is not None:
                    # Waninterface exists, modify.
                    waninterface_id = modify_waninterface(config_waninterface, waninterface_id, waninterfaces_n2id,
                                                          site_id)

                else:
                    # Waninterface does not exist, create.
                    waninterface_id = create_waninterface(config_waninterface, waninterfaces_n2id, site_id)

                # remove from delete queue
                leftover_waninterfaces = [entry for entry in leftover_waninterfaces if entry != waninterface_id]

            # Because WAN Interfaces may get renamed via the above, we need to update the n2id cache now.
            # We update it in the functions, however this may cause behavior where the script will work
            # because on this run, we can find old name -> Waninterface ID bindings, but it will fail on next run.
            # Better to trim these out, and fail on the interface runs if someone renames the Waninterface
            # and forgets to update the Interface binding. Cost, 1 API call.. :(
            waninterfaces_resp = sdk.get.waninterfaces(site_id)
            # Don't refresh leftover_waninterfaces though, that would be BAD..
            waninterfaces_cache, _ = extract_items(waninterfaces_resp, 'waninterfaces')
            waninterfaces_n2id = build_lookup_dict(waninterfaces_cache)

            # -- End WAN Interfaces

            # -- Start LAN Networks
            lannetworks_resp = sdk.get.lannetworks(site_id)
            lannetworks_cache, leftover_lannetworks = extract_items(lannetworks_resp, 'lannetworks')
            lannetworks_n2id = build_lookup_dict(lannetworks_cache)

            # iterate configs
            for config_lannetwork_name, config_lannetwork_value in config_lannetworks.items():
                # recombine object
                config_lannetwork = recombine_named_key_value(config_lannetwork_name, config_lannetwork_value,
                                                              name_key='name')

                # no need to get wan interface config, no child config objects.

                # Determine lannetwork ID.
                # look for implicit ID in object.
                implicit_lannetwork_id = config_lannetwork.get('id')
                name_lannetwork_id = lannetworks_n2id.get(config_lannetwork_name)

                if implicit_lannetwork_id is not None:
                    lannetwork_id = implicit_lannetwork_id

                elif name_lannetwork_id is not None:
                    # look up ID by name on existing lannetworks.
                    lannetwork_id = name_lannetwork_id
                else:
                    # no lannetwork object.
                    lannetwork_id = None

                # Create or modify lannetwork.
                if lannetwork_id is not None:
                    # Lannetwork exists, modify.
                    lannetwork_id = modify_lannetwork(config_lannetwork, lannetwork_id, lannetworks_n2id,
                                                      site_id)

                else:
                    # Lannetwork does not exist, create.
                    lannetwork_id = create_lannetwork(config_lannetwork, lannetworks_n2id, site_id)

                # remove from delete queue
                leftover_lannetworks = [entry for entry in leftover_lannetworks if entry != lannetwork_id]
            # -- End LAN Networks

            # -- Start DHCPSERVER config
            dhcpservers_resp = sdk.get.dhcpservers(site_id)
            dhcpservers_cache, leftover_dhcpservers = extract_items(dhcpservers_resp, 'dhcpserver')
            # build lookup cache based on subnet in each entry.
            dhcpservers_n2id = build_lookup_dict(dhcpservers_cache, key_val='subnet')

            # iterate configs (list)
            for config_dhcpserver_entry in config_dhcpservers:

                # deepcopy to modify.
                config_dhcpserver_record = copy.deepcopy(config_dhcpserver_entry)

                # no need to get dhcpserver config, no child config objects.

                # Determine dhcpserver ID.
                # look for implicit ID in object.
                implicit_dhcpserver_id = config_dhcpserver_entry.get('id')
                # NAME in essense for DHCP server is the subnet.
                config_dhcpserver_name = config_dhcpserver_entry.get('subnet')
                name_dhcpserver_id = dhcpservers_n2id.get(config_dhcpserver_name)

                if implicit_dhcpserver_id is not None:
                    dhcpserver_id = implicit_dhcpserver_id

                elif name_dhcpserver_id is not None:
                    # look up ID by name on existing interfaces.
                    dhcpserver_id = name_dhcpserver_id

                else:
                    # no dhcpserver object.
                    dhcpserver_id = None

                # Create or modify dhcpserver.
                if dhcpserver_id is not None:
                    # Dhcpserver exists, modify.
                    dhcpserver_id = modify_dhcpserver(config_dhcpserver_record, dhcpserver_id, site_id)

                else:
                    # Dhcpserver does not exist, create.
                    dhcpserver_id = create_dhcpserver(config_dhcpserver_record, site_id)

                # remove from delete queue
                leftover_dhcpservers = [entry for entry in leftover_dhcpservers if entry != dhcpserver_id]
            # -- End DHCPSERVER config

            # -- Start Site_extensions
            site_extensions_resp = sdk.get.site_extensions(site_id)
            site_extensions_cache, leftover_site_extensions = extract_items(site_extensions_resp,
                                                                            'site_extensions')
            site_extensions_n2id = build_lookup_dict(site_extensions_cache)

            # iterate configs
            for config_site_extension_name, config_site_extension_value in config_site_extensions.items():

                # recombine object
                config_site_extension = recombine_named_key_value(config_site_extension_name,
                                                                  config_site_extension_value,
                                                                  name_key='name')

                # no need to get site_extension config, no child config objects.

                # Determine site_extension ID.
                # look for implicit ID in object.
                implicit_site_extension_id = config_site_extension.get('id')
                name_site_extension_id = site_extensions_n2id.get(config_site_extension_name)

                if implicit_site_extension_id is not None:
                    site_extension_id = implicit_site_extension_id

                elif name_site_extension_id is not None:
                    # look up ID by name on existing site_extensions.
                    site_extension_id = name_site_extension_id
                else:
                    # no site_extension object.
                    site_extension_id = None

                # Create or modify site_extension.
                if site_extension_id is not None:
                    # Site_extension exists, modify.
                    site_extension_id = modify_site_extension(config_site_extension, site_extension_id,
                                                              site_extensions_n2id,
                                                              waninterfaces_n2id,
                                                              lannetworks_n2id, site_id)

                else:
                    # Site_extension does not exist, create.
                    site_extension_id = create_site_extension(config_site_extension,
                                                              site_extensions_n2id,
                                                              waninterfaces_n2id,
                                                              lannetworks_n2id, site_id)

                # remove from delete queue
                leftover_site_extensions = [entry for entry in leftover_site_extensions
                                            if entry != site_extension_id]

            # -- End Site_extensions

            # -- Start Site_securityzones
            site_securityzones_resp = sdk.get.sitesecurityzones(site_id)
            site_securityzones_cache, leftover_site_securityzones = extract_items(site_securityzones_resp,
                                                                                  'sitesecurityzones')
            # build lookup cache based on zone id.
            site_securityzones_zoneid2id = build_lookup_dict(site_securityzones_cache, key_val='zone_id')

            # iterate configs (list)
            for config_site_securityzone_entry in config_site_security_zones:

                # deepcopy to modify.
                config_site_securityzone = copy.deepcopy(config_site_securityzone_entry)

                # no need to get site_securityzone config, no child config objects.

                # Determine site_securityzone ID.
                # look for implicit ID in object.
                implicit_site_securityzone_id = config_site_securityzone.get('id')
                # if no ID, select by zone ID
                config_site_securityzone_zone = config_site_securityzone.get('zone_id')
                # do name to id lookup
                config_site_securityzone_zone_id = securityzones_n2id.get(config_site_securityzone_zone,
                                                                          config_site_securityzone_zone)
                # finally, get securityzone ID from zone_id
                config_site_securityzone_id = site_securityzones_zoneid2id.get(config_site_securityzone_zone_id)

                if implicit_site_securityzone_id is not None:
                    site_securityzone_id = implicit_site_securityzone_id

                elif config_site_securityzone_id is not None:
                    # look up ID by destinationprefix on existing site_securityzone.
                    site_securityzone_id = config_site_securityzone_id

                else:
                    # no site_securityzone object.
                    site_securityzone_id = None

                # Create or modify site_securityzone.
                if site_securityzone_id is not None:
                    # Site_securityzone exists, modify.
                    site_securityzone_id = modify_site_securityzone(config_site_securityzone, site_securityzone_id,
                                                                    waninterfaces_n2id, lannetworks_n2id, site_id)

                else:
                    # Site_securityzone does not exist, create.
                    site_securityzone_id = create_site_securityzone(config_site_securityzone, waninterfaces_n2id,
                                                                    lannetworks_n2id, site_id)

                # remove from delete queue
                leftover_site_securityzones = [entry for entry in leftover_site_securityzones
                                               if entry != site_securityzone_id]

            # -- End Site_securityzones

            # -- Start Spoke Clusters
            spokeclusters_resp = sdk.get.spokeclusters(site_id)
            spokeclusters_cache, leftover_spokeclusters = extract_items(spokeclusters_resp, 'spokeclusters')
            spokeclusters_n2id = build_lookup_dict(spokeclusters_cache)

            # iterate configs
            for config_spokecluster_name, config_spokecluster_value in config_spokeclusters.items():
                # recombine object
                config_spokecluster = recombine_named_key_value(config_spokecluster_name, config_spokecluster_value,
                                                                name_key='name')

                # no need to get Spoke Cluster config, no child config objects.

                # Determine spokecluster ID.
                # look for implicit ID in object.
                implicit_spokecluster_id = config_spokecluster.get('id')
                name_spokecluster_id = spokeclusters_n2id.get(config_spokecluster_name)

                if implicit_spokecluster_id is not None:
                    spokecluster_id = implicit_spokecluster_id

                elif name_spokecluster_id is not None:
                    # look up ID by name on existing spokeclusters.
                    spokecluster_id = name_spokecluster_id
                else:
                    # no spokecluster object.
                    spokecluster_id = None

                # Create or modify spokecluster.
                if spokecluster_id is not None:
                    # Spokecluster exists, modify.
                    spokecluster_id = modify_spokecluster(config_spokecluster, spokecluster_id, spokeclusters_n2id,
                                                          site_id)

                else:
                    # Spokecluster does not exist, create.
                    spokecluster_id = create_spokecluster(config_spokecluster, spokeclusters_n2id, site_id)

                # remove from delete queue
                leftover_spokeclusters = [entry for entry in leftover_spokeclusters if entry != spokecluster_id]

            # -- End Spoke Clusters

            # -- Start Elements - Iterate loop.
            # Get all elements assigned to this site from the global element cache.
            leftover_elements = [entry.get('id') for entry in elements_cache if entry.get('site_id') == site_id]

            for config_element_name, config_element_value in config_elements.items():
                # recombine element object
                config_element = recombine_named_key_value(config_element_name, config_element_value, name_key='name')

                # parse element config
                config_interfaces, config_routing, config_syslog, config_ntp, config_snmp, \
                    config_toolkit, config_element_extensions, config_element_security_zones \
                    = parse_element_config(config_element)

                config_serial, matching_element, matching_machine, matching_model = detect_elements(config_element)

                # deal with claiming elements
                while config_serial != matching_element.get('serial_number'):
                    output_message(" Serial {0} is not CLAIMED, attempting to claim..".format(config_serial))

                    claim_element(matching_machine, wait_if_offline=timeout_offline, wait_verify_success=timeout_claim,
                                  wait_interval=interval_timeout)

                    # refresh elements cache before detect.
                    update_element_machine_cache()
                    config_serial, matching_element, matching_machine, matching_model = detect_elements(config_element)

                # wait for claim to finish,
                # update matching_element as well in case of updated ETAG, to save a full cache refresh (do that later).
                matching_element = wait_for_element_state(matching_element, wait_verify_success=timeout_state,
                                                          wait_interval=interval_timeout)

                # at this point element will be claimed.

                # Check elements and upgrade if necessary
                upgrade_element(matching_element, config_element, wait_upgrade_timeout=timeout_upgrade,
                                pause_for_upgrade=wait_upgrade,
                                wait_interval=interval_timeout)

                # Have to refresh cache here, due to the fact that element _etag may change during upgrade.
                update_element_machine_cache()
                config_serial, matching_element, matching_machine, matching_model = detect_elements(config_element)

                # assign and configure element
                assign_modify_element(matching_element, site_id, config_element)

                # wait for element assignment. Update element record in case etag changes.
                matching_element = wait_for_element_state(matching_element, ['bound'],
                                                          wait_verify_success=timeout_state,
                                                          wait_interval=interval_timeout)

                # update element and machine cache before moving on.
                update_element_machine_cache()
                config_serial, matching_element, matching_machine, matching_model = detect_elements(config_element)

                # final element ID and model for this element:
                element_id = matching_element.get('id')
                element_model = matching_element.get('model_name')

                # remove this element from delete queue
                leftover_elements = [entry for entry in leftover_elements if entry != element_id]
                # -- End Elements

                # -- Start Interfaces
                interfaces_resp = sdk.get.interfaces(site_id, element_id)
                interfaces_cache, leftover_interfaces = extract_items(interfaces_resp, 'interfaces')
                interfaces_n2id = build_lookup_dict(interfaces_cache)
                # Create a lookup table for funny_name(s).
                # Funny name: A name in the config file that is unable to be used (interface doesn't support it), or
                # unable to be used (incorrect subif or port name). This table keeps that info, and lets it
                # be used if it doesn't conflict with actual interface names.
                interfaces_funny_n2id = {}

                # START LOOPBACKS ADD: need to handle base interfaces (bypass members) first. Get the looback IF deltas.
                config_loopback_add, api_loopback_del, \
                    config_loopback_n2id = get_loopback_lists(config_interfaces, interfaces_cache, interfaces_n2id)
                interfaces_funny_n2id.update(config_loopback_n2id)

                local_debug("CONFIG_LOOPBACK_ADD: ", config_loopback_add)

                # do add loopback now
                added_loopback_list = []
                for config_loopback_name, config_loopback_value in config_loopback_add.items():
                    # recombine object
                    config_interface = recombine_named_key_value(config_loopback_name, config_loopback_value,
                                                                 name_key='name')

                    added_loopback = create_interface(config_interface, interfaces_n2id, waninterfaces_n2id,
                                                      lannetworks_n2id, site_id, element_id)

                    # save the loopback IFs added, so later we can just modify non-added loopbacks.
                    added_loopback_list.append(added_loopback)

                # update interfaces cache now that all base interfaces are present.
                interfaces_resp = sdk.get.interfaces(site_id, element_id)
                interfaces_cache, _ = extract_items(interfaces_resp, 'interfaces')
                interfaces_n2id = build_lookup_dict(interfaces_cache)
                # get the looback IF deltas again.
                config_loopback_add, api_loopback_del, \
                    config_loopback_n2id = get_loopback_lists(config_interfaces, interfaces_cache, interfaces_n2id)
                interfaces_funny_n2id.update(config_loopback_n2id)

                # END LOOPBACKS ADD (need modify and delete )
                # refresh interfaces as ones were added.
                interfaces_resp = sdk.get.interfaces(site_id, element_id)
                interfaces_cache, leftover_interfaces = extract_items(interfaces_resp, 'interfaces')
                interfaces_n2id_api = build_lookup_dict(interfaces_cache)
                interfaces_id2n = build_lookup_dict(interfaces_cache, key_val='id', value_val='name')

                # extend interfaces_n2id with the loopback funny_name cache, Make sure API interfaces trump funny names
                interfaces_n2id = copy.deepcopy(interfaces_funny_n2id)
                interfaces_n2id.update(interfaces_n2id_api)

                # START DEFAULT INTERFACES

                # Get element defaults - these are the DEFAULT CONFIGs for this model.
                # If an interface is not specified in the config, it gets it's default config.
                config_interfaces_defaults = get_default_ifconfig_from_model_string(element_model)
                local_debug("CONFIG_INTERFACES_DEFAULT ONLOAD: ", config_interfaces_defaults)

                # Get bypasspairs for default
                config_bypasspairs_defaults = get_config_interfaces_by_type(config_interfaces_defaults, 'bypasspair')

                # figure out if we need default bypass pairs. If interface is defined in YAML config,
                # default bypasspairs will need to be ignored in final config.
                config_bypasspairs_defaults_if2bp, _ = get_parent_child_dict(config_bypasspairs_defaults,
                                                                             id2n=interfaces_id2n)

                # iterate the bypasspair defaults
                configured_interface_name_list = config_interfaces.keys()
                for ifname in config_bypasspairs_defaults_if2bp.keys():
                    # if specified config for one of the default members is present, remove the "default"
                    # bypass pair from config.

                    local_debug("DEFAULT BYPASS ITERATION: {0}, in {1}".format(ifname, configured_interface_name_list))
                    if ifname in configured_interface_name_list:
                        # delete default config as it has a config.
                        # the if2bp lookup is a list, but will always be 1 item. Grab the first one.
                        read_bypasspair_name = config_bypasspairs_defaults_if2bp.get(ifname, [])[0]
                        # check for reversed backwards
                        default_bypasspair_name = default_backwards_bypasspairs.get(read_bypasspair_name,
                                                                                    read_bypasspair_name)
                        local_debug("CONFIG_INTERFACES_DEFAULT B4 BPP-R: ", config_interfaces_defaults)
                        # check if another bypasspair default memeber already removed the default BPP
                        if config_interfaces_defaults.get(default_bypasspair_name):
                            del config_interfaces_defaults[default_bypasspair_name]

                # get parent/child mappings for delete
                config_parent2child, \
                    config_child2parent = get_parent_child_dict(config_interfaces_defaults,
                                                                id2n=interfaces_id2n)

                parent_interfaces = config_parent2child.keys()
                # delete default interface configs for bypass members
                for ifname in list(config_interfaces_defaults.keys()):
                    if ifname in parent_interfaces:
                        local_debug("PARENT DELETE: {0}".format(ifname), parent_interfaces)
                        # this IF is a member of a default bypass pair. Remove the config from the queue.
                        # If bypass pair doesn't already exist, member port configs dont need to be modified
                        # as they will be wiped on create of bypasspair automatically by this script.
                        del config_interfaces_defaults[ifname]
                    elif ifname in skip_interface_list:
                        # this is an unconfigurable interface, remove it from default config.
                        del config_interfaces_defaults[ifname]

                # Ok, now we need to get child/parent mappings for the user-specified config.
                # default interface configs should not be used if they will be a parent - they
                # will be set appropriately on child creation.
                # get parent/child mappings for delete
                config_parent2child, \
                    config_child2parent = get_parent_child_dict(config_interfaces,
                                                                id2n=interfaces_id2n)

                # delete default interface configs for config parents
                parent_interfaces = config_parent2child.keys()
                for ifname in list(config_interfaces_defaults.keys()):
                    if ifname in parent_interfaces:
                        local_debug("PARENT DELETE: {0}".format(ifname), parent_interfaces)
                        # this if is a parent of a user configured subif/bypasspair. Remove the config from the queue.
                        # If child if does not already exist, member port configs should be wiped
                        # on create of bypasspair.
                        del config_interfaces_defaults[ifname]

                # now that default bypasspairs are cleaned up, apply specified config to default.
                config_interfaces_defaults.update(config_interfaces)
                config_bypasspairs = get_config_interfaces_by_type(config_interfaces_defaults, 'bypasspair')
                local_debug("CONFIG_INTERFACES_WITH_DEFAULTS: ", config_interfaces_defaults)

                # END DEFAULT INTERFACES
                # START BYPASSPAIR

                # get full parent/child maps
                config_parent2child, config_child2parent = get_parent_child_dict(config_interfaces_defaults,
                                                                                 id2n=interfaces_id2n)
                local_debug("CONFIG_PARENT2CHILD: ", config_parent2child)
                local_debug("CONFIG_CHILD2PARENT: ", config_child2parent)

                # We need to delete unused bypasspairs NOW due to the fact other interfaces need them.
                # Get a list of all currently configured bypasspairs.
                interfaces_bypasspairs_cache = get_api_interfaces_by_type(interfaces_cache, 'bypasspair')
                leftover_bypasspairs = [entry['id'] for entry in interfaces_bypasspairs_cache if entry.get('id')]

                # Remove configured interfaces's parents from delete queue.
                # because if it is a parent, we don't want to try to delete it.
                # Exception is currently service link, as parent for service link can be changed.
                config_parent_interfaces = config_parent2child.keys()
                for config_parent_interface in config_parent_interfaces:
                    # try to get bypass if ID from the list of parent IF names, if the BP is a parent.
                    config_parent_interface_id = get_bypass_id_from_name(config_parent_interface, interfaces_n2id,
                                                                         funny_n2id=interfaces_funny_n2id)
                    if config_parent_interface_id:
                        # if we find one, make sure it isn't in delete queue
                        local_debug("PARENT BYPASS ID, REMOVING FROM DELETE QUEUE: ", config_parent_interface_id)
                        leftover_bypasspairs = [entry for entry in leftover_bypasspairs if
                                                entry != config_parent_interface_id]

                # iterate through config, remove IDs of config-referenced Bypasspairs.
                for config_interface_name, config_interface_value in config_bypasspairs.items():
                    # recombine object
                    config_interface = recombine_named_key_value(config_interface_name, config_interface_value,
                                                                 name_key='name')

                    # Determine interface ID.
                    # look for implicit ID in object.
                    implicit_interface_id = config_interface.get('id')
                    name_interface_id = get_bypass_id_from_name(config_interface_name, interfaces_n2id,
                                                                funny_n2id=interfaces_funny_n2id)
                    parent_interface_id = get_bypass_id_from_parent(config_interface.get('bypass_pair', {}),
                                                                    interfaces_bypasspairs_cache, interfaces_n2id,
                                                                    funny_n2id=interfaces_funny_n2id)
                    if implicit_interface_id is not None:
                        interface_id = implicit_interface_id
                    elif name_interface_id is not None:
                        # look up ID by name on existing interfaces.
                        interface_id = name_interface_id
                    elif parent_interface_id is not None:
                        # found based on parent match.
                        interface_id = parent_interface_id
                    else:
                        # no interface object.
                        interface_id = None

                    # remove from delete queue
                    leftover_bypasspairs = [entry for entry in leftover_bypasspairs if entry != interface_id]

                # DELETE unused bypasspairs at this point.
                delete_interfaces(leftover_bypasspairs, site_id, element_id, id2n=interfaces_id2n)

                # Go back through config, and now create/modify existing bypasspairs.
                for config_interface_name, config_interface_value in config_bypasspairs.items():
                    local_debug("DO BYPASSPAIR: {0}".format(config_interface_name), config_interface_value)
                    # recombine object
                    config_interface = recombine_named_key_value(config_interface_name, config_interface_value,
                                                                 name_key='name')

                    # Determine interface ID.
                    # look for implicit ID in object.
                    implicit_interface_id = config_interface.get('id')
                    name_interface_id = get_bypass_id_from_name(config_interface_name, interfaces_n2id,
                                                                funny_n2id=interfaces_funny_n2id)
                    parent_interface_id = get_bypass_id_from_parent(config_interface.get('bypass_pair', {}),
                                                                    interfaces_bypasspairs_cache, interfaces_n2id,
                                                                    funny_n2id=interfaces_funny_n2id)
                    if implicit_interface_id is not None:
                        interface_id = implicit_interface_id

                    elif name_interface_id is not None:
                        # look up ID by name on existing interfaces.
                        interface_id = name_interface_id
                    elif parent_interface_id is not None:
                        # found based on parent match.
                        interface_id = parent_interface_id
                    else:
                        # no interface object.
                        interface_id = None

                    # Create or modify interface.
                    if interface_id is not None:
                        # Interface exists, modify.
                        interface_id = modify_interface(config_interface, interface_id, interfaces_n2id,
                                                        waninterfaces_n2id, lannetworks_n2id, site_id, element_id,
                                                        interfaces_funny_n2id=interfaces_funny_n2id)

                    else:
                        # Interface does not exist, create.
                        interface_id = create_interface(config_interface, interfaces_n2id, waninterfaces_n2id,
                                                        lannetworks_n2id, site_id, element_id,
                                                        interfaces_funny_n2id=interfaces_funny_n2id)

                    # no need for delete queue, as already deleted.

                # END BYPASSPAIRS
                # START LOOPBACKS MODIFY

                config_loopbacks = get_config_interfaces_by_type(config_interfaces_defaults, 'loopback')
                for config_interface_name, config_interface_value in config_loopbacks.items():

                    local_debug("IF: {0}, PARENT2CHILD".format(config_interface_name),
                                config_parent2child.keys())
                    # look for unconfigurable interfaces.
                    if config_interface_name in skip_interface_list:
                        throw_warning("Interface {0} is not configurable.".format(config_interface_name))
                        # dont configure this interface, break out of loop.
                        continue
                    # look for parent interface
                    elif config_interface_name in config_parent2child.keys():
                        throw_warning("Cannot configure interface {0}, it is set as a parent for {1}."
                                      "".format(config_interface_name,
                                                ", ".join(config_parent2child.get(config_interface_name))))
                        # skip this interface
                        continue

                    # recombine object
                    config_interface = recombine_named_key_value(config_interface_name, config_interface_value,
                                                                 name_key='name')

                    # no need to get interface config, no child config objects.

                    # Determine interface ID.
                    # look for implicit ID in object.
                    implicit_interface_id = config_interface.get('id')
                    # Loopbacks name is unsettable, use parent ID for location.
                    name_interface_id = interfaces_n2id.get(config_interface_name)

                    if implicit_interface_id is not None:
                        interface_id = implicit_interface_id

                    elif name_interface_id is not None:
                        # look up ID by name on existing interfaces.
                        interface_id = name_interface_id
                    else:
                        # no interface object.
                        interface_id = None

                    # check if interface_id was already added.
                    if interface_id in added_loopback_list:
                        # this interface was added above. Skip.
                        continue

                    # Create or modify interface.
                    if interface_id is not None:
                        # Interface exists, modify.
                        interface_id = modify_interface(config_interface, interface_id, interfaces_n2id,
                                                        waninterfaces_n2id, lannetworks_n2id, site_id,
                                                        element_id,
                                                        interfaces_funny_n2id=interfaces_funny_n2id)

                    else:
                        # no loopbacks should ever get added here, but keep code just in case something falls through.
                        # Interface does not exist, create.
                        interface_id = create_interface(config_interface, interfaces_n2id, waninterfaces_n2id,
                                                        lannetworks_n2id, site_id, element_id,
                                                        interfaces_funny_n2id=interfaces_funny_n2id)

                    # delete queue was already determined in the loopback order pre-add function above.

                # create a leftover_loopbacks construct from the api_loopback_del output from get_loopback_lists
                leftover_loopbacks = [entry['id'] for entry in api_loopback_del if entry.get('id')]

                # END Loopbacks
                # START PPPoE

                # extend interfaces_n2id with the funny_name cache, Make sure API interfaces trump funny names
                current_interfaces_n2id_holder = interfaces_n2id
                interfaces_n2id = copy.deepcopy(interfaces_funny_n2id)
                interfaces_n2id.update(current_interfaces_n2id_holder)

                config_pppoe = get_config_interfaces_by_type(config_interfaces_defaults, 'pppoe')
                leftover_pppoe = get_api_interfaces_name_by_type(interfaces_cache, 'pppoe', key_name='id')
                for config_interface_name, config_interface_value in config_pppoe.items():

                    local_debug("IF: {0}, PARENT2CHILD".format(config_interface_name), config_parent2child.keys())
                    # look for unconfigurable interfaces.
                    if config_interface_name in skip_interface_list:
                        throw_warning("Interface {0} is not configurable.".format(config_interface_name))
                        # dont configure this interface, break out of loop.
                        continue
                    # look for parent interface
                    elif config_interface_name in config_parent2child.keys():
                        throw_warning("Cannot configure interface {0}, it is set as a parent for {1}."
                                      "".format(config_interface_name,
                                                ", ".join(config_parent2child.get(config_interface_name))))
                        # skip this interface
                        continue

                    # recombine object
                    config_interface = recombine_named_key_value(config_interface_name, config_interface_value,
                                                                 name_key='name')

                    # no need to get interface config, no child config objects.

                    # Determine interface ID.
                    # look for implicit ID in object.
                    implicit_interface_id = config_interface.get('id')
                    # PPPoE name is unsettable, use parent ID for location.
                    name_interface_id = get_pppoe_id(config_interface, interfaces_cache, interfaces_n2id)

                    if implicit_interface_id is not None:
                        interface_id = implicit_interface_id

                    elif name_interface_id is not None:
                        # look up ID by name on existing interfaces.
                        interface_id = name_interface_id
                    else:
                        # no interface object.
                        interface_id = None

                    # Create or modify interface.
                    if interface_id is not None:
                        # Interface exists, modify.
                        interface_id = modify_interface(config_interface, interface_id, interfaces_n2id,
                                                        waninterfaces_n2id, lannetworks_n2id, site_id, element_id,
                                                        interfaces_funny_n2id=interfaces_funny_n2id)

                    else:
                        # Interface does not exist, create.
                        interface_id = create_interface(config_interface, interfaces_n2id, waninterfaces_n2id,
                                                        lannetworks_n2id, site_id, element_id,
                                                        interfaces_funny_n2id=interfaces_funny_n2id)

                    # remove from delete queue
                    leftover_pppoe = [entry for entry in leftover_pppoe if entry != interface_id]

                # END PPPoE
                # START SUBINTERFACE

                # extend interfaces_n2id with the funny_name cache, Make sure API interfaces trump funny names
                current_interfaces_n2id_holder = interfaces_n2id
                interfaces_n2id = copy.deepcopy(interfaces_funny_n2id)
                interfaces_n2id.update(current_interfaces_n2id_holder)

                config_subinterfaces = get_config_interfaces_by_type(config_interfaces_defaults, 'subinterface')
                leftover_subinterfaces = get_api_interfaces_name_by_type(interfaces_cache, 'subinterface',
                                                                         key_name='id')
                for config_interface_name, config_interface_value in config_subinterfaces.items():

                    local_debug("IF: {0}, PARENT2CHILD".format(config_interface_name), config_parent2child.keys())
                    # look for unconfigurable interfaces.
                    if config_interface_name in skip_interface_list:
                        throw_warning("Interface {0} is not configurable.".format(config_interface_name))
                        # dont configure this interface, break out of loop.
                        continue
                    # look for parent interface
                    elif config_interface_name in config_parent2child.keys():
                        throw_warning("Cannot configure interface {0}, it is set as a parent for {1}."
                                      "".format(config_interface_name,
                                                ", ".join(config_parent2child.get(config_interface_name))))
                        # skip this interface
                        continue

                    # recombine object
                    config_interface = recombine_named_key_value(config_interface_name, config_interface_value,
                                                                 name_key='name')

                    # no need to get interface config, no child config objects.

                    # Determine interface ID.
                    # look for implicit ID in object.
                    implicit_interface_id = config_interface.get('id')
                    # Subif has name constraints, check via items in config instead of a possible typo name.
                    name_interface_id = get_subif_id(config_interface, interfaces_cache, interfaces_n2id)

                    if implicit_interface_id is not None:
                        interface_id = implicit_interface_id

                    elif name_interface_id is not None:
                        # look up ID by name on existing interfaces.
                        interface_id = name_interface_id
                    else:
                        # no interface object.
                        interface_id = None

                    # Create or modify interface.
                    if interface_id is not None:
                        # Interface exists, modify.
                        interface_id = modify_interface(config_interface, interface_id, interfaces_n2id,
                                                        waninterfaces_n2id, lannetworks_n2id, site_id, element_id,
                                                        interfaces_funny_n2id=interfaces_funny_n2id)

                    else:
                        # Interface does not exist, create.
                        interface_id = create_interface(config_interface, interfaces_n2id, waninterfaces_n2id,
                                                        lannetworks_n2id, site_id, element_id,
                                                        api_interfaces_cache=interfaces_cache,
                                                        interfaces_funny_n2id=interfaces_funny_n2id)

                    # remove from delete queue
                    leftover_subinterfaces = [entry for entry in leftover_subinterfaces if entry != interface_id]

                # END SUBINTERFACE
                # START PORTS

                # extend interfaces_n2id with the funny_name cache, Make sure API interfaces trump funny names
                current_interfaces_n2id_holder = interfaces_n2id
                interfaces_n2id = copy.deepcopy(interfaces_funny_n2id)
                interfaces_n2id.update(current_interfaces_n2id_holder)

                config_ports = get_config_interfaces_by_type(config_interfaces_defaults, 'port')
                # Ports are never deleted, and will be set to default if not referenced.
                # iterate configs
                for config_interface_name, config_interface_value in config_ports.items():

                    local_debug("IF: {0}, PARENT2CHILD".format(config_interface_name), config_parent2child.keys())
                    # look for unconfigurable interfaces.
                    if config_interface_name in skip_interface_list:
                        throw_warning("Interface {0} is not configurable.".format(config_interface_name))
                        # dont configure this interface, break out of loop.
                        continue
                    # look for parent interface
                    elif config_interface_name in config_parent2child.keys():
                        throw_warning("Cannot use configuration for interface {0}, it is set as a parent for {1}."
                                      "".format(config_interface_name,
                                                ", ".join(config_parent2child.get(config_interface_name))))
                        # skip this interface
                        continue

                    # recombine object
                    config_interface = recombine_named_key_value(config_interface_name, config_interface_value,
                                                                 name_key='name')

                    # no need to get interface config, no child config objects.

                    # Determine interface ID.
                    # look for implicit ID in object.
                    implicit_interface_id = config_interface.get('id')
                    name_interface_id = interfaces_n2id.get(config_interface_name)

                    if implicit_interface_id is not None:
                        interface_id = implicit_interface_id

                    elif name_interface_id is not None:
                        # look up ID by name on existing interfaces.
                        interface_id = name_interface_id
                    else:
                        # no interface object.
                        interface_id = None

                    # Create or modify interface.
                    if interface_id is not None:
                        # Interface exists, modify.
                        interface_id = modify_interface(config_interface, interface_id, interfaces_n2id,
                                                        waninterfaces_n2id, lannetworks_n2id, site_id, element_id,
                                                        interfaces_funny_n2id=interfaces_funny_n2id)

                    else:
                        # Interface does not exist, create.
                        interface_id = create_interface(config_interface, interfaces_n2id, waninterfaces_n2id,
                                                        lannetworks_n2id, site_id, element_id,
                                                        interfaces_funny_n2id=interfaces_funny_n2id)

                    # no delete queue for 'port' class ports.

                # END PORTS
                # START SERVICELINK

                # extend interfaces_n2id with the funny_name cache, Make sure API interfaces trump funny names
                current_interfaces_n2id_holder = interfaces_n2id
                interfaces_n2id = copy.deepcopy(interfaces_funny_n2id)
                interfaces_n2id.update(current_interfaces_n2id_holder)

                config_servicelinks = get_config_interfaces_by_type(config_interfaces_defaults, 'service_link')
                leftover_servicelinks = get_api_interfaces_name_by_type(interfaces_cache, 'service_link', key_name='id')
                for config_interface_name, config_interface_value in config_servicelinks.items():

                    local_debug("IF: {0}, PARENT2CHILD".format(config_interface_name), config_parent2child.keys())
                    # look for unconfigurable interfaces.
                    if config_interface_name in skip_interface_list:
                        throw_warning("Interface {0} is not configurable.".format(config_interface_name))
                        # dont configure this interface, break out of loop.
                        continue
                    # look for parent interface
                    elif config_interface_name in config_parent2child.keys():
                        throw_warning("Cannot configure interface {0}, it is set as a parent for {1}."
                                      "".format(config_interface_name,
                                                ", ".join(config_parent2child.get(config_interface_name))))
                        # skip this interface
                        continue

                    # recombine object
                    config_interface = recombine_named_key_value(config_interface_name, config_interface_value,
                                                                 name_key='name')

                    # no need to get interface config, no child config objects.

                    # Determine interface ID.
                    # look for implicit ID in object.
                    implicit_interface_id = config_interface.get('id')
                    name_interface_id = interfaces_n2id.get(config_interface_name)

                    if implicit_interface_id is not None:
                        interface_id = implicit_interface_id

                    elif name_interface_id is not None:
                        # look up ID by name on existing interfaces.
                        interface_id = name_interface_id
                    else:
                        # no interface object.
                        interface_id = None

                    # Create or modify interface.
                    if interface_id is not None:
                        # Interface exists, modify.
                        interface_id = modify_interface(config_interface, interface_id, interfaces_n2id,
                                                        waninterfaces_n2id, lannetworks_n2id, site_id, element_id,
                                                        interfaces_funny_n2id=interfaces_funny_n2id)

                    else:
                        # Interface does not exist, create.
                        interface_id = create_interface(config_interface, interfaces_n2id, waninterfaces_n2id,
                                                        lannetworks_n2id, site_id, element_id,
                                                        interfaces_funny_n2id=interfaces_funny_n2id)

                    # remove from delete queue
                    leftover_servicelinks = [entry for entry in leftover_servicelinks if entry != interface_id]

                # END SERVICELINK

                # ------------------
                # BEGIN INTERFACE CLEANUP.

                # Don't need to update interfaces_id2n, as interfaces queued for deletion should have already
                # existed when it was created before the bypasspair step.

                # cleanup - delete unused servicelinks
                delete_interfaces(leftover_servicelinks, site_id, element_id, id2n=interfaces_id2n)

                # cleanup - delete unused subinterfaces
                delete_interfaces(leftover_subinterfaces, site_id, element_id, id2n=interfaces_id2n)

                # cleanup - delete unused pppoe
                delete_interfaces(leftover_pppoe, site_id, element_id, id2n=interfaces_id2n)

                # cleanup - delete unused loopbacks
                delete_interfaces(leftover_loopbacks, site_id, element_id, id2n=interfaces_id2n)

                # update Interface caches before continuing.
                interfaces_resp = sdk.get.interfaces(site_id, element_id)
                interfaces_cache, leftover_interfaces = extract_items(interfaces_resp, 'interfaces')
                interfaces_n2id_api = build_lookup_dict(interfaces_cache)
                interfaces_id2n = build_lookup_dict(interfaces_cache, key_val='id', value_val='name')

                # extend interfaces_n2id with the funny_name cache, Make sure API interfaces trump funny names
                interfaces_n2id = copy.deepcopy(interfaces_funny_n2id)
                interfaces_n2id.update(interfaces_n2id_api)
                # -- End Interfaces

                # -- Start Element Spoke HA config
                # Since for some reason, Spoke HA config is tied into element object, we can't configure it
                # at the same time as the element configuration operation is performed. This requires us to do
                # a second element operation AFTER the interfaces are enumerated and at the correct state (here).

                # assign and configure element
                handle_element_spoke_ha(matching_element, site_id, config_element, interfaces_n2id, spokeclusters_n2id)

                # update element and machine cache before moving on.
                update_element_machine_cache()
                config_serial, matching_element, matching_machine, matching_model = detect_elements(config_element)

                # final element ID and model for this element:
                element_id = matching_element.get('id')
                element_model = matching_element.get('model_name')

                # -- End Element Spoke HA config

                # -- Start Routing
                # parse routing config.
                config_routing_aspathaccesslists, config_routing_ipcommunitylists, config_routing_prefixlists, \
                    config_routing_routemaps, config_routing_static, \
                    config_routing_bgp = parse_routing_config(config_routing)

                # parse BGP config
                config_routing_bgp_global, config_routing_bgp_peers = parse_bgp_config(config_routing_bgp)

                # START AS-PATH_ACCESS_LISTS
                aspath_access_lists_resp = sdk.get.routing_aspathaccesslists(site_id, element_id)
                aspath_access_lists_cache, leftover_aspath_access_lists = extract_items(aspath_access_lists_resp,
                                                                                        'as_path_access_lists')
                aspath_access_lists_n2id = build_lookup_dict(aspath_access_lists_cache)

                # iterate configs
                for config_aspath_access_list_name, config_aspath_access_list_value in \
                        config_routing_aspathaccesslists.items():

                    # recombine object
                    config_aspath_access_list = recombine_named_key_value(config_aspath_access_list_name,
                                                                          config_aspath_access_list_value,
                                                                          name_key='name')

                    # no need to get aspath_access_list config, no child config objects.

                    # Determine aspath_access_list ID.
                    # look for implicit ID in object.
                    implicit_aspath_access_list_id = config_aspath_access_list.get('id')
                    name_aspath_access_list_id = aspath_access_lists_n2id.get(config_aspath_access_list_name)

                    if implicit_aspath_access_list_id is not None:
                        aspath_access_list_id = implicit_aspath_access_list_id

                    elif name_aspath_access_list_id is not None:
                        # look up ID by name on existing aspath_access_lists.
                        aspath_access_list_id = name_aspath_access_list_id
                    else:
                        # no aspath_access_list object.
                        aspath_access_list_id = None

                    # Check for auto-generated items, these cannot be modified.
                    auto_generated = config_aspath_access_list.get('auto_generated')

                    if auto_generated:
                        throw_warning("AS-PATH Access List {0} is auto_generated. Skipping."
                                      "".format(config_aspath_access_list_name))
                        # Remove from delete queue, if we think it exists:
                        if aspath_access_list_id is not None:
                            # remove from delete queue
                            leftover_aspath_access_lists = [entry for entry in leftover_aspath_access_lists
                                                            if entry != aspath_access_list_id]

                        # don't configure this aspath_access_list, break out of loop.
                        continue

                    # Create or modify aspath_access_list.
                    if aspath_access_list_id is not None:
                        # aspath_access_list exists, modify.
                        aspath_access_list_id = modify_aspath_access_list(config_aspath_access_list,
                                                                          aspath_access_list_id,
                                                                          aspath_access_lists_n2id, site_id, element_id)

                    else:
                        # aspath_access_list does not exist, create.
                        aspath_access_list_id = create_aspath_access_list(config_aspath_access_list,
                                                                          aspath_access_lists_n2id, site_id, element_id)

                    # remove from delete queue
                    leftover_aspath_access_lists = [entry for entry in leftover_aspath_access_lists
                                                    if entry != aspath_access_list_id]

                # END AS-PATH_ACCESS_LISTS

                # START IP_COMMUNITY_LISTS
                ip_community_lists_resp = sdk.get.routing_ipcommunitylists(site_id, element_id)
                ip_community_lists_cache, leftover_ip_community_lists = extract_items(ip_community_lists_resp,
                                                                                      'ip_community_lists')
                ip_community_lists_n2id = build_lookup_dict(ip_community_lists_cache)

                # iterate configs
                for config_ip_community_list_name, config_ip_community_list_value in \
                        config_routing_ipcommunitylists.items():

                    # recombine object
                    config_ip_community_list = recombine_named_key_value(config_ip_community_list_name,
                                                                         config_ip_community_list_value,
                                                                         name_key='name')

                    # no need to get ip_community_list config, no child config objects.

                    # Determine ip_community_list ID.
                    # look for implicit ID in object.
                    implicit_ip_community_list_id = config_ip_community_list.get('id')
                    name_ip_community_list_id = ip_community_lists_n2id.get(config_ip_community_list_name)

                    if implicit_ip_community_list_id is not None:
                        ip_community_list_id = implicit_ip_community_list_id

                    elif name_ip_community_list_id is not None:
                        # look up ID by name on existing ip_community_lists.
                        ip_community_list_id = name_ip_community_list_id
                    else:
                        # no ip_community_list object.
                        ip_community_list_id = None

                    # Check for auto-generated items, these cannot be modified.
                    auto_generated = config_ip_community_list.get('auto_generated')

                    if auto_generated:
                        throw_warning("IP Community List {0} is auto_generated. Skipping."
                                      "".format(config_ip_community_list_name))
                        # Remove from delete queue, if we think it exists:
                        if ip_community_list_id is not None:
                            # remove from delete queue
                            leftover_ip_community_lists = [entry for entry in leftover_ip_community_lists
                                                           if entry != ip_community_list_id]

                        # don't configure this ip_community_list, break out of loop.
                        continue

                    # Create or modify ip_community_list.
                    if ip_community_list_id is not None:
                        # ip_community_list exists, modify.
                        ip_community_list_id = modify_ip_community_list(config_ip_community_list,
                                                                        ip_community_list_id,
                                                                        ip_community_lists_n2id, site_id, element_id)

                    else:
                        # ip_community_list does not exist, create.
                        ip_community_list_id = create_ip_community_list(config_ip_community_list,
                                                                        ip_community_lists_n2id, site_id, element_id)

                    # remove from delete queue
                    leftover_ip_community_lists = [entry for entry in leftover_ip_community_lists
                                                   if entry != ip_community_list_id]

                # END IP_COMMUNITY_LISTS

                # START PREFIXLISTS
                prefixlists_resp = sdk.get.routing_prefixlists(site_id, element_id)
                prefixlists_cache, leftover_prefixlists = extract_items(prefixlists_resp, 'prefixlists')
                prefixlists_n2id = build_lookup_dict(prefixlists_cache)

                # iterate configs
                for config_prefixlist_name, config_prefixlist_value in \
                        config_routing_prefixlists.items():

                    # recombine object
                    config_prefixlist = recombine_named_key_value(config_prefixlist_name,
                                                                  config_prefixlist_value,
                                                                  name_key='name')

                    # no need to get prefixlist config, no child config objects.

                    # Determine prefixlist ID.
                    # look for implicit ID in object.
                    implicit_prefixlist_id = config_prefixlist.get('id')
                    name_prefixlist_id = prefixlists_n2id.get(config_prefixlist_name)

                    if implicit_prefixlist_id is not None:
                        prefixlist_id = implicit_prefixlist_id

                    elif name_prefixlist_id is not None:
                        # look up ID by name on existing prefixlists.
                        prefixlist_id = name_prefixlist_id
                    else:
                        # no prefixlist object.
                        prefixlist_id = None

                    # Check for auto-generated items, these cannot be modified.
                    auto_generated = config_prefixlist.get('auto_generated')

                    if auto_generated:
                        throw_warning("Routing Prefix List {0} is auto_generated. Skipping."
                                      "".format(config_prefixlist_name))
                        # Remove from delete queue, if we think it exists:
                        if prefixlist_id is not None:
                            # remove from delete queue
                            leftover_prefixlists = [entry for entry in leftover_prefixlists
                                                    if entry != prefixlist_id]

                        # don't configure this prefixlist, break out of loop.
                        continue

                    # Create or modify prefixlist.
                    if prefixlist_id is not None:
                        # prefixlist exists, modify.
                        prefixlist_id = modify_prefixlist(config_prefixlist,
                                                          prefixlist_id,
                                                          prefixlists_n2id, site_id, element_id)

                    else:
                        # prefixlist does not exist, create.
                        prefixlist_id = create_prefixlist(config_prefixlist,
                                                          prefixlists_n2id, site_id, element_id)

                    # remove from delete queue
                    leftover_prefixlists = [entry for entry in leftover_prefixlists
                                            if entry != prefixlist_id]

                # END PREFIXLISTS

                # START ROUTEMAPS
                routemaps_resp = sdk.get.routing_routemaps(site_id, element_id)
                routemaps_cache, leftover_routemaps = extract_items(routemaps_resp, 'routemaps')
                routemaps_n2id = build_lookup_dict(routemaps_cache)

                # iterate configs
                for config_routemap_name, config_routemap_value in \
                        config_routing_routemaps.items():

                    # recombine object
                    config_routemap = recombine_named_key_value(config_routemap_name,
                                                                config_routemap_value,
                                                                name_key='name')

                    # no need to get routemap config, no child config objects.

                    # Determine routemap ID.
                    # look for implicit ID in object.
                    implicit_routemap_id = config_routemap.get('id')
                    name_routemap_id = routemaps_n2id.get(config_routemap_name)

                    if implicit_routemap_id is not None:
                        routemap_id = implicit_routemap_id

                    elif name_routemap_id is not None:
                        # look up ID by name on existing routemaps.
                        routemap_id = name_routemap_id
                    else:
                        # no routemap object.
                        routemap_id = None

                    # Check for auto-generated items, these cannot be modified.
                    auto_generated = config_routemap.get('auto_generated')

                    if auto_generated:
                        throw_warning("Route Map {0} is auto_generated. Skipping."
                                      "".format(config_routemap_name))
                        # Remove from delete queue, if we think it exists:
                        if routemap_id is not None:
                            # remove from delete queue
                            leftover_routemaps = [entry for entry in leftover_routemaps
                                                  if entry != routemap_id]

                        # don't configure this routemap, break out of loop.
                        continue

                    # Create or modify routemap.
                    if routemap_id is not None:
                        # routemap exists, modify.
                        routemap_id = modify_routemap(config_routemap, routemap_id, routemaps_n2id,
                                                      aspath_access_lists_n2id, ip_community_lists_n2id,
                                                      prefixlists_n2id, site_id, element_id)

                    else:
                        # routemap does not exist, create.
                        routemap_id = create_routemap(config_routemap,
                                                      routemaps_n2id, aspath_access_lists_n2id, ip_community_lists_n2id,
                                                      prefixlists_n2id, site_id, element_id)

                    # remove from delete queue
                    leftover_routemaps = [entry for entry in leftover_routemaps
                                          if entry != routemap_id]

                # END ROUTEMAPS

                # START BGP GLOBAL
                # no need to get BGP Global config, no child config objects.

                # No need to determine BGP Global (bgpconfigs), one object per element.

                bgp_global_id = modify_bgp_global(config_routing_bgp_global, site_id, element_id)

                # END BGP GLOBAL

                # START BGP PEERS
                bgp_peers_resp = sdk.get.bgppeers(site_id, element_id)
                bgp_peers_cache, leftover_bgp_peers = extract_items(bgp_peers_resp, 'bgp_peers')
                bgp_peers_n2id = build_lookup_dict(bgp_peers_cache)
                # build lookup cache based on peer IP as well.
                bgp_peers_p2id = build_lookup_dict(bgp_peers_cache, key_val='peer_ip')

                # iterate configs
                for config_bgp_peer_name, config_bgp_peer_value in \
                        config_routing_bgp_peers.items():

                    # recombine object
                    config_bgp_peer = recombine_named_key_value(config_bgp_peer_name,
                                                                config_bgp_peer_value,
                                                                name_key='name')

                    # no need to get bgp_peer config, no child config objects.

                    # Determine bgp_peer ID.
                    # look for implicit ID in object.
                    implicit_bgp_peer_id = config_bgp_peer.get('id')
                    # Attempt to look up ID by name
                    name_bgp_peer_id = bgp_peers_n2id.get(config_bgp_peer_name)
                    # Attempt to look up ID by peer IP
                    config_bgp_peer_peer_ip = config_bgp_peer.get('peer_ip')
                    peer_ip_bgp_peer_id = bgp_peers_p2id.get(config_bgp_peer_peer_ip)

                    if implicit_bgp_peer_id is not None:
                        bgp_peer_id = implicit_bgp_peer_id

                    elif peer_ip_bgp_peer_id is not None:
                        # look up ID by peer IP on existing bgp_peers.
                        bgp_peer_id = peer_ip_bgp_peer_id

                    elif name_bgp_peer_id is not None:
                        # look up ID by name on existing bgp_peers.
                        bgp_peer_id = name_bgp_peer_id
                    else:
                        # no bgp_peer object.
                        bgp_peer_id = None

                    # Create or modify bgp_peer.
                    if bgp_peer_id is not None:
                        # bgp_peer exists, modify.
                        bgp_peer_id = modify_bgp_peer(config_bgp_peer, bgp_peer_id, bgp_peers_n2id,
                                                      routemaps_n2id, site_id, element_id)

                    else:
                        # bgp_peer does not exist, create.
                        bgp_peer_id = create_bgp_peer(config_bgp_peer, bgp_peers_n2id, routemaps_n2id,
                                                      site_id, element_id)

                    # remove from delete queue
                    leftover_bgp_peers = [entry for entry in leftover_bgp_peers
                                          if entry != bgp_peer_id]
                # END BGP PEERS

                # START STATIC ROUTING
                staticroutes_resp = sdk.get.staticroutes(site_id, element_id)
                staticroutes_cache, leftover_staticroutes = extract_items(staticroutes_resp, 'staticroutes')
                # build lookup cache based on prefix.
                staticroutes_n2id = build_lookup_dict(staticroutes_cache, key_val='destination_prefix')

                # iterate configs (list)
                for config_staticroute_entry in config_routing_static:

                    # deepcopy to modify.
                    config_staticroute = copy.deepcopy(config_staticroute_entry)

                    # no need to get staticroute config, no child config objects.

                    # Determine staticroute ID.
                    # look for implicit ID in object.
                    implicit_staticroute_id = config_staticroute.get('id')
                    config_interface_destinationprefix = config_staticroute.get('destination_prefix')
                    destinationprefix_staticroute_id = staticroutes_n2id.get(config_interface_destinationprefix)

                    if implicit_staticroute_id is not None:
                        staticroute_id = implicit_staticroute_id

                    elif destinationprefix_staticroute_id is not None:
                        # look up ID by destinationprefix on existing staticroute.
                        staticroute_id = destinationprefix_staticroute_id

                    else:
                        # no staticroute object.
                        staticroute_id = None

                    # Create or modify staticroute.
                    if staticroute_id is not None:
                        # Staticroute exists, modify.
                        staticroute_id = modify_staticroute(config_staticroute, staticroute_id, interfaces_n2id,
                                                            site_id, element_id)

                    else:
                        # Staticroute does not exist, create.
                        staticroute_id = create_staticroute(config_staticroute, interfaces_n2id,
                                                            site_id, element_id)

                    # remove from delete queue
                    leftover_staticroutes = [entry for entry in leftover_staticroutes if entry != staticroute_id]

                # END STATIC ROUTING

                # -- End Routing

                # -- Start SNMP
                # parse SNMP config.
                config_snmp_agent, config_snmp_traps = parse_snmp_config(config_snmp)

                # SNMP AGENT first.
                snmp_agents_resp = sdk.get.snmpagents(site_id, element_id)
                snmp_agents_cache, leftover_snmp_agents = extract_items(snmp_agents_resp, 'snmp_agents')

                # iterate configs (list)
                for config_snmp_agent_entry in config_snmp_agent:

                    # deepcopy to modify.
                    config_snmp_agent = copy.deepcopy(config_snmp_agent_entry)

                    # no need to get snmp_agent config, no child config objects.

                    # Determine snmp_agent ID.
                    # look for implicit ID in object.
                    implicit_snmp_agent_id = config_snmp_agent.get('id')

                    # only one SNMP agent per element. check cache.
                    existing_snmp_agent_id = None
                    if len(snmp_agents_cache) > 0:
                        # get first entry ID, as there should be only 1
                        existing_snmp_agent_id = snmp_agents_cache[0].get('id')

                    if implicit_snmp_agent_id is not None:
                        snmp_agent_id = implicit_snmp_agent_id

                    elif existing_snmp_agent_id is not None:
                        # look up ID on existing agent.
                        snmp_agent_id = existing_snmp_agent_id

                    else:
                        # no snmp_agent object.
                        snmp_agent_id = None

                    # Create or modify snmp_agent.
                    if snmp_agent_id is not None:
                        # Snmp_agent exists, modify.
                        snmp_agent_id = modify_snmp_agent(config_snmp_agent, snmp_agent_id, interfaces_n2id,
                                                          site_id, element_id)

                    else:
                        # Snmp_agent does not exist, create.
                        snmp_agent_id = create_snmp_agent(config_snmp_agent, interfaces_n2id,
                                                          site_id, element_id)

                    # remove from delete queue
                    leftover_snmp_agents = [entry for entry in leftover_snmp_agents if entry != snmp_agent_id]

                # SNMP TRAPS second.
                snmp_traps_resp = sdk.get.snmptraps(site_id, element_id)
                snmp_traps_cache, leftover_snmp_traps = extract_items(snmp_traps_resp, 'snmp_traps')
                # build lookup cache based on server + version. Have to do manually.
                snmp_traps_n2id = build_lookup_dict_snmp_trap(snmp_traps_cache)

                # iterate configs (list)
                for config_snmp_trap_entry in config_snmp_traps:

                    # deepcopy to modify.
                    config_snmp_trap = copy.deepcopy(config_snmp_trap_entry)

                    # no need to get snmp_trap config, no child config objects.

                    # Determine snmp_trap ID.
                    # look for implicit ID in object.
                    implicit_snmp_trap_id = config_snmp_trap.get('id')
                    config_server_ip = config_snmp_trap.get('server_ip')
                    config_version = config_snmp_trap.get('version')
                    server_version_snmp_trap_id = snmp_traps_n2id.get("{0}+{1}".format(config_server_ip,
                                                                                       config_version))

                    if implicit_snmp_trap_id is not None:
                        snmp_trap_id = implicit_snmp_trap_id

                    elif server_version_snmp_trap_id is not None:
                        # look up ID on existing agent.
                        snmp_trap_id = server_version_snmp_trap_id

                    else:
                        # no snmp_trap object.
                        snmp_trap_id = None

                    # Create or modify snmp_trap.
                    if snmp_trap_id is not None:
                        # Snmp_trap exists, modify.
                        snmp_trap_id = modify_snmp_trap(config_snmp_trap, snmp_trap_id, interfaces_n2id,
                                                        site_id, element_id)

                    else:
                        # Snmp_trap does not exist, create.
                        snmp_trap_id = create_snmp_trap(config_snmp_trap, interfaces_n2id,
                                                        site_id, element_id)

                    # remove from delete queue
                    leftover_snmp_traps = [entry for entry in leftover_snmp_traps if entry != snmp_trap_id]

                # -- End SNMP

                # -- Start SYSLOG config
                syslogs_resp = sdk.get.syslogservers(site_id, element_id)
                syslogs_cache, leftover_syslogs = extract_items(syslogs_resp, 'syslog')
                # build lookup cache based on prefix.
                syslogs_n2id = build_lookup_dict(syslogs_cache)

                # iterate configs (list)
                for config_syslog_entry in config_syslog:

                    # deepcopy to modify.
                    config_syslog_record = copy.deepcopy(config_syslog_entry)

                    # no need to get syslog config, no child config objects.

                    # Determine syslog ID.
                    # look for implicit ID in object.
                    implicit_syslog_id = config_syslog_entry.get('id')
                    config_syslog_name = config_syslog_entry.get('name')
                    name_syslog_id = syslogs_n2id.get(config_syslog_name)

                    if implicit_syslog_id is not None:
                        syslog_id = implicit_syslog_id

                    elif name_syslog_id is not None:
                        # look up ID by name on existing interfaces.
                        syslog_id = name_syslog_id

                    else:
                        # no syslog object.
                        syslog_id = None

                    # Create or modify syslog.
                    if syslog_id is not None:
                        # Syslog exists, modify.
                        syslog_id = modify_syslog(config_syslog_record, syslog_id, interfaces_n2id, site_id, element_id)

                    else:
                        # Syslog does not exist, create.
                        syslog_id = create_syslog(config_syslog_record, interfaces_n2id, site_id, element_id)

                    # remove from delete queue
                    leftover_syslogs = [entry for entry in leftover_syslogs if entry != syslog_id]
                # -- End SYSLOG config

                # -- Start NTP config
                ntps_resp = sdk.get.ntp(element_id)
                ntps_cache, leftover_ntps = extract_items(ntps_resp, 'ntp')
                # build lookup cache based on prefix.
                ntps_n2id = build_lookup_dict(ntps_cache)

                # iterate configs (list)
                for config_ntp_entry in config_ntp:

                    # deepcopy to modify.
                    config_ntp_record = copy.deepcopy(config_ntp_entry)

                    # no need to get ntp config, no child config objects.

                    # Determine ntp ID.
                    # look for implicit ID in object.
                    implicit_ntp_id = config_ntp_entry.get('id')
                    config_ntp_name = config_ntp_entry.get('name')
                    name_ntp_id = ntps_n2id.get(config_ntp_name)

                    if implicit_ntp_id is not None:
                        ntp_id = implicit_ntp_id

                    elif name_ntp_id is not None:
                        # look up ID by name on existing interfaces.
                        ntp_id = name_ntp_id

                    else:
                        # no ntp object.
                        ntp_id = None

                    # Create or modify ntp.
                    if ntp_id is not None:
                        # Ntp exists, modify.
                        ntp_id = modify_ntp(config_ntp_record, ntp_id, interfaces_n2id, site_id, element_id)

                    else:
                        # Ntp does not exist, create.
                        ntp_id = create_ntp(config_ntp_record, interfaces_n2id, site_id, element_id)

                    # remove from delete queue
                    leftover_ntps = [entry for entry in leftover_ntps if entry != ntp_id]
                # -- End NTP config

                # -- Start Element_extensions
                element_extensions_resp = sdk.get.element_extensions(site_id, element_id)
                element_extensions_cache, leftover_element_extensions = extract_items(element_extensions_resp,
                                                                                      'element_extensions')
                element_extensions_n2id = build_lookup_dict(element_extensions_cache)

                # iterate configs
                for config_element_extension_name, config_element_extension_value in config_element_extensions.items():

                    # recombine object
                    config_element_extension = recombine_named_key_value(config_element_extension_name,
                                                                         config_element_extension_value,
                                                                         name_key='name')

                    # no need to get element_extension config, no child config objects.

                    # Determine element_extension ID.
                    # look for implicit ID in object.
                    implicit_element_extension_id = config_element_extension.get('id')
                    name_element_extension_id = element_extensions_n2id.get(config_element_extension_name)

                    if implicit_element_extension_id is not None:
                        element_extension_id = implicit_element_extension_id

                    elif name_element_extension_id is not None:
                        # look up ID by name on existing element_extensions.
                        element_extension_id = name_element_extension_id
                    else:
                        # no element_extension object.
                        element_extension_id = None

                    # Create or modify element_extension.
                    if element_extension_id is not None:
                        # Element_extension exists, modify.
                        element_extension_id = modify_element_extension(config_element_extension, element_extension_id,
                                                                        element_extensions_n2id,
                                                                        waninterfaces_n2id,
                                                                        lannetworks_n2id,
                                                                        interfaces_n2id, site_id, element_id)

                    else:
                        # Element_extension does not exist, create.
                        element_extension_id = create_element_extension(config_element_extension,
                                                                        element_extensions_n2id,
                                                                        waninterfaces_n2id,
                                                                        lannetworks_n2id,
                                                                        interfaces_n2id, site_id, element_id)

                    # remove from delete queue
                    leftover_element_extensions = [entry for entry in leftover_element_extensions
                                                   if entry != element_extension_id]

                # -- End Element_extensions

                # -- Start element_securityzones
                element_securityzones_resp = sdk.get.elementsecurityzones(site_id, element_id)
                element_securityzones_cache, leftover_element_securityzones = extract_items(element_securityzones_resp,
                                                                                            'elementsecurityzones')
                # build lookup cache based on zone id.
                element_securityzones_zoneid2id = build_lookup_dict(element_securityzones_cache, key_val='zone_id')

                # iterate configs (list)
                for config_element_securityzone_entry in config_element_security_zones:

                    # deepcopy to modify.
                    config_element_securityzone = copy.deepcopy(config_element_securityzone_entry)

                    # no need to get element_securityzone config, no child config objects.

                    # Determine element_securityzone ID.
                    # look for implicit ID in object.
                    implicit_element_securityzone_id = config_element_securityzone.get('id')
                    # if no ID, select by zone ID
                    config_element_securityzone_zone = config_element_securityzone.get('zone_id')
                    # do name to id lookup
                    config_element_securityzone_zone_id = securityzones_n2id.get(config_element_securityzone_zone,
                                                                                 config_element_securityzone_zone)
                    # finally, get securityzone ID from zone_id
                    config_element_securityzone_id = element_securityzones_zoneid2id.get(
                        config_element_securityzone_zone_id)

                    if implicit_element_securityzone_id is not None:
                        element_securityzone_id = implicit_element_securityzone_id

                    elif config_element_securityzone_id is not None:
                        # look up ID by destinationprefix on existing element_securityzone.
                        element_securityzone_id = config_element_securityzone_id

                    else:
                        # no element_securityzone object.
                        element_securityzone_id = None

                    # Create or modify element_securityzone.
                    if element_securityzone_id is not None:
                        # element_securityzone exists, modify.
                        element_securityzone_id = modify_element_securityzone(config_element_securityzone,
                                                                              element_securityzone_id,
                                                                              waninterfaces_n2id, lannetworks_n2id,
                                                                              interfaces_n2id, site_id, element_id)

                    else:
                        # element_securityzone does not exist, create.
                        element_securityzone_id = create_element_securityzone(config_element_securityzone,
                                                                              waninterfaces_n2id,
                                                                              lannetworks_n2id, interfaces_n2id,
                                                                              site_id, element_id)

                    # remove from delete queue
                    leftover_element_securityzones = [entry for entry in leftover_element_securityzones
                                                      if entry != element_securityzone_id]

                # -- End element_securityzones

                # -- Start Toolkit (elementaccess) - single object
                # no need to get toolkit config, no child config objects.

                # No need to determine elementaccess ID, one object per element.

                toolkit_id = modify_toolkit(config_toolkit, site_id, element_id)

                # -- End Toolkit

                # ------------------
                # BEGIN ELEMENT CLEANUP

                # Toolkit is single object, no cleanup required.

                # delete remaining element_securityzone configs
                # build a element_securityzone_id to zone name mapping.
                element_securityzones_id2zoneid = build_lookup_dict(element_securityzones_cache, key_val='id',
                                                                    value_val='zone_id')
                delete_element_securityzones(leftover_element_securityzones, site_id, element_id,
                                             id2n=element_securityzones_id2zoneid)

                # delete remaining element_extension configs
                element_extensions_id2n = build_lookup_dict(element_extensions_cache, key_val='id', value_val='name')
                delete_element_extensions(leftover_element_extensions, site_id, element_id,
                                          id2n=element_extensions_id2n)

                # delete remaining ntp configs
                ntps_id2n = build_lookup_dict(ntps_cache, key_val='id', value_val='name')
                delete_ntps(leftover_ntps, site_id, element_id, id2n=ntps_id2n)

                # delete remaining syslog configs
                syslogs_id2n = build_lookup_dict(syslogs_cache, key_val='id', value_val='name')
                delete_syslogs(leftover_syslogs, site_id, element_id, id2n=syslogs_id2n)

                # delete remaining snmp agent configs
                delete_snmp_traps(leftover_snmp_traps, site_id, element_id)

                # delete remaining snmp agent configs
                delete_snmp_agents(leftover_snmp_agents, site_id, element_id)

                # delete remaining staticroutes
                delete_staticroutes(leftover_staticroutes, site_id, element_id)

                # delete remaining BGP PEERS
                bgp_peers_id2n = build_lookup_dict(bgp_peers_cache, key_val='id', value_val='name')
                delete_bgp_peers(leftover_bgp_peers, site_id, element_id, id2n=bgp_peers_id2n)

                # No deletes for BGP GLOBAL

                # delete remaining ROUTEMAPS
                routemaps_id2n = build_lookup_dict(routemaps_cache, key_val='id', value_val='name')
                delete_routemaps(leftover_routemaps, site_id, element_id, id2n=routemaps_id2n)

                # delete remaining PREFIXLISTS
                prefixlists_id2n = build_lookup_dict(prefixlists_cache, key_val='id', value_val='name')
                delete_prefixlists(leftover_prefixlists, site_id, element_id,
                                   id2n=prefixlists_id2n)

                # delete remaining IP_COMMUNITY_LISTS
                ip_community_lists_id2n = build_lookup_dict(ip_community_lists_cache,
                                                            key_val='id', value_val='name')
                delete_ip_community_lists(leftover_ip_community_lists, site_id, element_id,
                                          id2n=ip_community_lists_id2n)

                # delete remaining as_path_access_lists
                aspath_access_lists_id2n = build_lookup_dict(aspath_access_lists_cache,
                                                             key_val='id', value_val='name')
                delete_aspath_access_lists(leftover_aspath_access_lists, site_id, element_id,
                                           id2n=aspath_access_lists_id2n)

            # ------------------
            # BEGIN SITE CLEANUP.

            # unbind any remaining elements.
            unbind_elements(leftover_elements, site_id)
            # add declaim for failed unbind in future.

            # delete remaining spokecluster configs
            # build a spokecluster_id to name mapping.
            spokeclusters_id2n= build_lookup_dict(spokeclusters_cache, key_val='id', value_val='name')
            delete_spokeclusters(leftover_spokeclusters, site_id, id2n=spokeclusters_id2n)

            # delete remaining site_securityzone configs
            # build a site_securityzone_id to zone name mapping.
            site_securityzones_id2zoneid = build_lookup_dict(site_securityzones_cache, key_val='id',
                                                             value_val='zone_id')
            delete_site_securityzones(leftover_site_securityzones, site_id, id2n=site_securityzones_id2zoneid)

            # delete remaining site_extension configs
            site_extensions_id2n = build_lookup_dict(site_extensions_cache, key_val='id', value_val='name')
            delete_site_extensions(leftover_site_extensions, site_id, id2n=site_extensions_id2n)

            # delete remaining dhcpserver configs
            dhcpservers_id2n = build_lookup_dict(dhcpservers_cache, key_val='id', value_val='subnet')
            delete_dhcpservers(leftover_dhcpservers, site_id, id2n=dhcpservers_id2n)

            # cleanup - delete unused Lannetworks
            lannetworks_id2n = build_lookup_dict(lannetworks_cache, key_val='id', value_val='name')
            delete_lannetworks(leftover_lannetworks, site_id, id2n=lannetworks_id2n)

            # cleanup - delete unused Waninterfaces
            waninterfaces_id2n = build_lookup_dict(waninterfaces_cache, key_val='id', value_val='name')
            delete_waninterfaces(leftover_waninterfaces, site_id, id2n=waninterfaces_id2n)

            # set site state
            set_site_state(config_site, site_id)

    else:
        # Destroy!

        # -- Start Sites Prep - Iterate loop
        # build sites ID to name map from cache.
        sites_id2n = build_lookup_dict(sites_cache, key_val='id', value_val='name')

        for config_site_name, config_site_value in config_sites.items():
            # recombine site object
            config_site = recombine_named_key_value(config_site_name, config_site_value, name_key='name')

            # Determine site ID.
            # look for implicit ID in object.
            implicit_site_id = config_site.get('id')
            name_site_id = sites_n2id.get(config_site_name)

            if implicit_site_id is not None:
                del_site_id = implicit_site_id

            elif name_site_id is not None:
                # look up ID by name on existing sites.
                del_site_id = name_site_id
            else:
                # no site object.
                del_site_id = None
                throw_warning("Could not find site {0} ({1}). Continuing: ".format(config_site_name, del_site_id))

            del_site_name = sites_id2n.get(del_site_id, del_site_id)

            output_message("Beginning to DESTROY site {0}({1})..".format(del_site_name,
                                                                         del_site_id))

            # -- End Sites Prep

            # -- Start Elements
            # Get all elements assigned to this site from the global element cache.
            site_elements = [entry.get('id') for entry in elements_cache if entry.get('site_id') == del_site_id]

            # unbind the elements
            unbound_elements = unbind_elements(site_elements, del_site_id)
            # -- End Elements

            # -- Start WAN Interfaces
            waninterfaces_resp = sdk.get.waninterfaces(del_site_id)
            waninterfaces_cache, delete_waninterfaces_list = extract_items(waninterfaces_resp, 'waninterfaces')

            # build sites ID to name map from cache.
            waninterfaces_id2n = build_lookup_dict(waninterfaces_cache, key_val='id', value_val='name')

            # delete WAN interfaces
            delete_waninterfaces(delete_waninterfaces_list, del_site_id, id2n=waninterfaces_id2n)

            # -- End WAN Interfaces

            # disable site.
            output_message("Disabling site..")
            config_site['admin_state'] = 'disabled'
            set_site_state(config_site, del_site_id)

            # wait for element unbinds to complete
            for del_element in unbound_elements:
                wait_for_element_state(del_element, ['ready'], wait_verify_success=timeout_state,
                                       wait_interval=interval_timeout,destroy_declaim=destroy_declaim)

            # Delete site
            output_message("Deleting Site {0}..".format(del_site_name))
            del_site_resp = sdk.delete.sites(del_site_id)

            if not del_site_resp.cgx_status:
                throw_error("Could not delete site {0}: ".format(del_site_name),
                            del_site_resp.cgx_content)

    output_message("DONE")


def go():
    """
    Stub script entry point. Authenticates CloudGenix SDK, and gathers options from command line to run do_site()
    :return: No return
    """
    global debuglevel
    global sdk_debuglevel
    global sdk
    global timeout_offline
    global timeout_claim
    global timeout_upgrade
    global wait_upgrade
    global timeout_state
    global interval_timeout
    global force_update
    global site_safety_factor

    # Parse arguments
    parser = argparse.ArgumentParser(description="Create or Destroy site from YAML config file.")
    config_group = parser.add_argument_group('Config', 'These options change how the configuration is loaded.')
    config_group.add_argument('Config File', metavar='YAML CONFIG FILE', type=str, nargs=1,
                              help='Path to .yml file containing site config')
    config_group.add_argument("--timeout-offline", help="Default maximum time to wait to claim if an ION is offline.",
                              default=DEFAULT_WAIT_MAX_TIME, type=int)
    config_group.add_argument("--timeout-claim", help="Default maximum time to wait for an ION claim to complete",
                              default=DEFAULT_WAIT_MAX_TIME, type=int)
    config_group.add_argument("--timeout-upgrade", help="Default maximum time to wait for.",
                              default=DEFAULT_WAIT_MAX_TIME, type=int)
    config_group.add_argument("--wait-upgrade", help="When upgrading, wait for upgrade to complete. "
                                                     "Configuration changes for major element version changes "
                                                     "require upgrade to finish.",
                              default=True, action="store_false")
    config_group.add_argument("--timeout-state", help="Default maximum time for an ION to change state"
                                                      "(assign, un-assign).",
                              default=DEFAULT_WAIT_MAX_TIME, type=int)
    config_group.add_argument("--interval-timeout", help="Default timeout recheck interval for all timeouts "
                                                         "(10-180 seconds).",
                              default=DEFAULT_WAIT_INTERVAL, type=int)
    config_group.add_argument("--force-update", help="Force re-submission of configuration items to the API, even if "
                                                     "the objects have not changed.",
                              default=False, action="store_true")
    config_group.add_argument("--site-safety-factor", help="Maximum number of sites that can be modified at once by "
                                                           "this script. This is a safety switch to prevent the script"
                                                           " from inadvertently modifying a large number of sites.",
                              default=1, type=int)
    config_group.add_argument("--destroy", help="DESTROY site and all connected items (WAN Interfaces, LAN Networks).",
                              default=False, action="store_true")
    config_group.add_argument("--destroydeclaim", help="DESTROY site and all connected items (WAN Interfaces, LAN Networks). DECLAIM element",
                              default=False, action="store_true")

    # Allow Controller modification and debug level sets.
    controller_group = parser.add_argument_group('API', 'These options change how this program connects to the API.')
    controller_group.add_argument("--controller", "-C",
                                  help="Controller URI, ex. https://api.elcapitan.cloudgenix.com",
                                  default=None)

    login_group = parser.add_argument_group('Login', 'These options allow skipping of interactive login')
    login_group.add_argument("--email", "-E", help="Use this email as User Name instead of cloudgenix_settings.py "
                                                   "or prompting",
                             default=None)
    login_group.add_argument("--password", "-PW", help="Use this Password instead of cloudgenix_settings.py "
                                                       "or prompting",
                             default=None)
    login_group.add_argument("--insecure", "-I", help="Do not verify SSL certificate",
                             action='store_true',
                             default=False)
    login_group.add_argument("--noregion", "-NR", help="Ignore Region-based redirection.",
                             dest='ignore_region', action='store_true', default=False)

    debug_group = parser.add_argument_group('Debug', 'These options enable debugging output')
    debug_group.add_argument("--verbose", "-V", help="Verbosity of script output, levels 0-3", type=int,
                             default=1)
    debug_group.add_argument("--sdkdebug", "-D", help="Enable SDK Debug output, levels 0-2", type=int,
                             default=0)

    args = vars(parser.parse_args())

    destroy = args['destroy']
    destroy_declaim = args['destroydeclaim']
    if destroy_declaim:
        destroy = True

    config_file = args['Config File'][0]

    # load config file
    with open(config_file, 'r') as datafile:
        loaded_config = yaml.load(datafile)

    # set verbosity and SDK debug
    debuglevel = args["verbose"]
    sdk_debuglevel = args["sdkdebug"]

    # set config force update
    force_update = args["force_update"]

    # set default waits
    timeout_offline = args["timeout_offline"]
    timeout_claim = args["timeout_claim"]
    timeout_upgrade = args["timeout_upgrade"]
    wait_upgrade = args["wait_upgrade"]
    timeout_state = args["timeout_state"]
    interval_timeout = args["interval_timeout"]

    # set safety factor
    site_safety_factor = args["site_safety_factor"]

    # Build SDK Constructor
    if args['controller'] and args['insecure']:
        sdk = cloudgenix.API(controller=args['controller'], ssl_verify=False)
    elif args['controller']:
        sdk = cloudgenix.API(controller=args['controller'])
    elif args['insecure']:
        sdk = cloudgenix.API(ssl_verify=False)
    else:
        sdk = cloudgenix.API()

    # check for region ignore
    if args['ignore_region']:
        sdk.ignore_region = True

    # Verbosity, default = 1.
    # 0 = no output
    # 1 = print status messages
    # 2 = print info messages
    # 3 = print debug

    # SDK debug, default = 0
    # 0 = logger handlers removed, critical only
    # 1 = logger info messages
    # 2 = logger debug messages.

    if sdk_debuglevel == 1:
        # info msgs, CG SDK info
        logging.basicConfig(level=logging.INFO,
                            format="%(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s")
        logger.setLevel(logging.INFO)
        sdk.set_debug(1)
    elif sdk_debuglevel >= 2:
        # debug msgs, CG SDK debug
        logging.basicConfig(level=logging.DEBUG,
                            format="%(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s")
        logger.setLevel(logging.DEBUG)
        sdk.set_debug(2)

    else:
        # Remove all handlers
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        # set logging level to default
        logger.setLevel(logging.WARNING)

    # login logic. Use cmdline if set, use AUTH_TOKEN next, finally user/pass from config file, then prompt.
    # figure out user
    if args["email"]:
        user_email = args["email"]
    elif CLOUDGENIX_USER:
        user_email = CLOUDGENIX_USER
    else:
        user_email = None

    # figure out password
    if args["password"]:
        user_password = args["password"]
    elif CLOUDGENIX_PASSWORD:
        user_password = CLOUDGENIX_PASSWORD
    else:
        user_password = None

    # check for token
    if CLOUDGENIX_AUTH_TOKEN and not args["email"] and not args["password"]:
        sdk.interactive.use_token(CLOUDGENIX_AUTH_TOKEN)
        if sdk.tenant_id is None:
            throw_error("AUTH_TOKEN login failure, please check token.")

    else:
        while sdk.tenant_id is None:
            sdk.interactive.login(user_email, user_password)
            # clear after one failed login, force relogin.
            if not sdk.tenant_id:
                user_email = None
                user_password = None
    # Do the real work
    try:
        do_site(loaded_config, destroy, destroy_declaim)
    except CloudGenixConfigError:
        # Exit silently if error hit.
        sys.exit(1)
