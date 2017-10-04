"""NApp that solve the L2 Learning Switch algorithm."""

from kytos.core import KytosEvent, KytosNApp, log
from kytos.core.helpers import listen_to
from pyof.foundation.network_types import Ethernet
from pyof.v0x04.asynchronous.packet_in import PacketInReason
from pyof.v0x04.controller2switch.flow_mod import FlowMod, FlowModCommand
from pyof.v0x04.controller2switch.packet_out import PacketOut
from pyof.v0x04.common.port import PortNo
from pyof.v0x04.common.flow_instructions import InstructionApplyAction
from pyof.v0x04.common.action import ActionOutput
from pyof.v0x04.common.flow_match import OxmOfbMatchField, OxmTLV

from napps.renanrb.of_l2ls13 import settings


class Main(KytosNApp):
    """Main class of a KytosNApp, responsible for OpenFlow operations."""

    def setup(self):
        """App initialization (used instead of ``__init__``).

        The setup method is automatically called by the run method.
        Users shouldn't call this method directly.
        """
        pass

    def execute(self):
        """Method to be runned once on app 'start' or in a loop.

        The execute method is called by the run method of KytosNApp class.
        Users shouldn't call this method directly.
        """
        pass

    @listen_to('kytos/core.switches.new')
    def install_table_miss_flow(self, event):
        flow_mod = FlowMod()
        flow_mod.command = FlowModCommand.OFPFC_ADD

        action = ActionOutput(port=PortNo.OFPP_CONTROLLER)

        instruction = InstructionApplyAction()
        instruction.actions.append(action)

        flow_mod.instructions.append(instruction)

        destination = event.content['switch'].connection
        event_out = KytosEvent(name=('kytos/of_l2ls.messages.out.'
                                     'ofpt_flow_mod'),
                               content={'destination': destination,
                                        'message': flow_mod})
        self.controller.buffers.msg_out.put(event_out)

    @listen_to('kytos/of_core.v0x04.messages.in.ofpt_packet_in')
    def handle_packet_in(self, event):
        """Handle PacketIn Event.

        Install flows allowing communication between switch ports.

        Args:
            event (KytosPacketIn): Received Event
        """
        log.debug("PacketIn Received")

        packet_in = event.content['message']

        ethernet = Ethernet()
        ethernet.unpack(packet_in.data.value)

        # Ignore LLDP packets or packets not generated by table-miss flows
        if (ethernet.destination in settings.lldp_macs or
            packet_in.reason != PacketInReason.OFPR_NO_MATCH):
            return

        # Learn the port where the sender is connected
        in_port = packet_in.in_port

        switch = event.source.switch
        switch.update_mac_table(ethernet.source, in_port)

        ports = switch.where_is_mac(ethernet.destination)

        # Add a flow to the switch if the destination is known
        if ports:
            flow_mod = FlowMod()
            flow_mod.command = FlowModCommand.OFPFC_ADD
            flow_mod.priority = settings.flow_priority

            match_dl_type = OxmTLV()
            match_dl_type.oxm_field = OxmOfbMatchField.OFPXMT_OFB_ETH_TYPE
            match_dl_type.oxm_value = ethernet.ether_type.value.to_bytes(2,'big')
            flow_mod.match.oxm_match_fields.append(match_dl_type)

            match_dl_src = OxmTLV()
            match_dl_src.oxm_field = OxmOfbMatchField.OFPXMT_OFB_ETH_SRC
            match_dl_src.oxm_value = ethernet.source.pack()
            flow_mod.match.oxm_match_fields.append(match_dl_src)

            match_dl_dst = OxmTLV()
            match_dl_dst.oxm_field = OxmOfbMatchField.OFPXMT_OFB_ETH_DST
            match_dl_dst.oxm_value = ethernet.destination.pack()
            flow_mod.match.oxm_match_fields.append(match_dl_dst)

            action = ActionOutput(port=ports[0])

            instruction = InstructionApplyAction()
            instruction.actions.append(action)

            flow_mod.instructions.append(instruction)

            event_out = KytosEvent(name=('kytos/of_l2ls.messages.out.'
                                         'ofpt_flow_mod'),
                                   content={'destination': event.source,
                                            'message': flow_mod})
            self.controller.buffers.msg_out.put(event_out)

        # Send the packet to correct destination or flood it
        packet_out = PacketOut()
        packet_out.buffer_id = packet_in.buffer_id
        packet_out.in_port = in_port
        packet_out.data = packet_in.data

        port = ports[0] if ports else PortNo.OFPP_FLOOD

        out_action = ActionOutput(port=port)

        packet_out.actions.append(out_action)
        event_out = KytosEvent(name=('kytos/of_l2ls.messages.out.'
                                     'ofpt_packet_out'),
                               content={'destination': event.source,
                                        'message': packet_out})

        self.controller.buffers.msg_out.put(event_out)

    def shutdown(self):
        """Too simple to have a shutdown procedure."""
        pass
