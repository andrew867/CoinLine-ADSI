/* The test route delegates all ADSI encoding and signaling to res_adsi. */
#include "asterisk.h"

/*** MODULEINFO
    <depend>res_adsi</depend>
    <support_level>extended</support_level>
 ***/

#include "asterisk/adsi.h"
#include "asterisk/channel.h"
#include "asterisk/format_cache.h"
#include "asterisk/framehook.h"
#include "asterisk/indications.h"
#include "asterisk/module.h"
#include "asterisk/pbx.h"

static const char name[] = "CoinLineReference";

enum { packet_samples = 160 };

struct packet_padding {
    struct ast_frame frame;
    unsigned char data[AST_FRIENDLY_OFFSET + packet_samples];
};

/* Keep every native sample when the SIP codec receives a short final write. */
static struct ast_frame *pad_packet(struct ast_channel *channel, struct ast_frame *frame,
    enum ast_framehook_event event, void *data)
{
    struct packet_padding *padding = data;
    unsigned char *payload = padding->data + AST_FRIENDLY_OFFSET;

    if (event != AST_FRAMEHOOK_EVENT_WRITE || !frame || frame->frametype != AST_FRAME_VOICE
        || frame->subclass.format != ast_format_ulaw || frame->datalen <= 0 || frame->datalen >= packet_samples) {
        return frame;
    }
    memcpy(payload, frame->data.ptr, frame->datalen);
    memset(payload + frame->datalen, 0xff, packet_samples - frame->datalen);
    padding->frame = *frame;
    padding->frame.data.ptr = payload;
    padding->frame.offset = AST_FRIENDLY_OFFSET;
    padding->frame.datalen = packet_samples;
    padding->frame.samples = packet_samples;
    padding->frame.mallocd = 0;
    ast_frfree(frame);
    return &padding->frame;
}

static void free_padding(void *data)
{
    ast_free(data);
}

static int attach_padding(struct ast_channel *channel)
{
    int hook;
    struct ast_framehook_interface interface = {
        .version = AST_FRAMEHOOK_INTERFACE_VERSION,
        .event_cb = pad_packet,
        .destroy_cb = free_padding,
        .data = ast_calloc(1, sizeof(struct packet_padding)),
    };
    if (!interface.data) {
        return -1;
    }
    ast_channel_lock(channel);
    hook = ast_framehook_attach(channel, &interface);
    ast_channel_unlock(channel);
    if (hook < 0) {
        ast_free(interface.data);
    }
    return hook;
}

static int run_reference(struct ast_channel *channel, const char *args)
{
    unsigned char parameters[256];
    int length;

    if (ast_answer(channel) || ast_safe_sleep(channel, 250) || attach_padding(channel) < 0) {
        return -1;
    }
    /* The SIP driver starts as unavailable. Let the native CAS probe decide. */
    ast_channel_adsicpe_set(channel, AST_ADSI_UNKNOWN);
    if (ast_adsi_load_session(channel, NULL, 0, 1) != 1) {
        return -1;
    }
    length = ast_adsi_display(parameters, ADSI_INFO_PAGE, 1, ADSI_JUST_LEFT, 0, "LAB", "");
    if (length < 0) {
        return -1;
    }
    length += ast_adsi_set_line(parameters + length, ADSI_INFO_PAGE, 1);
    if (ast_adsi_transmit_message_full(channel, parameters, length, ADSI_MSG_DISPLAY, 0)) {
        return -1;
    }
    if (!ast_adsi_unload_session(channel)
        && !ast_playtones_start(channel, 3000, "1000/250", 0)) {
        ast_safe_sleep(channel, 500);
        ast_playtones_stop(channel);
    }
    return -1;
}

static int load_module(void)
{
    return ast_register_application(name, run_reference, "Native ADSI lab exchange", "Send a reference screen.");
}

static int unload_module(void)
{
    return ast_unregister_application(name);
}

AST_MODULE_INFO(ASTERISK_GPL_KEY, AST_MODFLAG_DEFAULT, "CoinLine native ADSI lab exchange",
    .load = load_module,
    .unload = unload_module,
    .requires = "res_adsi",
);
